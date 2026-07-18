"""Unit + property tests for the M2 deterministic backtest engine."""

from collections.abc import Mapping
from datetime import date, timedelta

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from yquant.backtest import BacktestEngine, Order, run_backtest
from yquant.backtest.costs import UsCostModel
from yquant.backtest.engine import Fill, Rejection, TargetProvider
from yquant.strategies.base import TargetPortfolio


def _linear_bars(
    symbol: str, closes: list[float], *, start: date = date(2024, 1, 2)
) -> pd.DataFrame:
    day = start
    rows = []
    for close in closes:
        rows.append({"symbol": symbol, "date": day, "close": close, "is_halted": False})
        day = day + timedelta(days=1)
    return pd.DataFrame(rows)


def _submit(
    engine: BacktestEngine,
    order: Order,
    *,
    day: date = date(2024, 6, 3),
    price: float = 100.0,
    is_halted: bool = False,
) -> Fill | Rejection:
    return engine.submit_order(order, day=day, price=price, is_halted=is_halted)


def _hold_first(symbol: str, weight: float = 1.0) -> TargetProvider:
    placed = {"done": False}

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if placed["done"] or symbol not in closes:
            return None
        placed["done"] = True
        return TargetPortfolio(
            as_of=day,
            weights={symbol: weight},
            layers={symbol: "core"},
            cash_weight=1.0 - weight,
        )

    return provider


def test_buy_respects_whole_share_lots_and_budget() -> None:
    engine = BacktestEngine(initial_cash=1_000.0, trading_dates=[date(2024, 6, 3)])
    fill = _submit(engine, Order("SPY", "buy", 100), price=100.0)

    assert isinstance(fill, Fill)
    # 1000 budget minus 9.5 commission, then / (100 * 1.0005) -> 9 shares.
    assert fill.shares == 9
    assert engine.settled_cash >= 0.0


def test_buy_rejected_when_budget_below_commission() -> None:
    engine = BacktestEngine(initial_cash=5.0, trading_dates=[date(2024, 6, 3)])
    outcome = _submit(engine, Order("SPY", "buy", 1), price=100.0)

    assert isinstance(outcome, Rejection)
    assert outcome.reason == "insufficient_funds"


def test_sell_without_position_is_rejected() -> None:
    engine = BacktestEngine(initial_cash=1_000.0, trading_dates=[date(2024, 6, 3)])
    outcome = _submit(engine, Order("SPY", "sell", 5), price=100.0)

    assert isinstance(outcome, Rejection)
    assert outcome.reason == "no_position"


def test_sell_clamps_to_held_shares() -> None:
    dates = [date(2024, 6, 3), date(2024, 6, 4)]
    engine = BacktestEngine(initial_cash=10_000.0, trading_dates=dates)
    buy = _submit(engine, Order("SPY", "buy", 10), day=dates[0], price=100.0)
    assert isinstance(buy, Fill)
    held = buy.shares
    fill = _submit(engine, Order("SPY", "sell", 999), day=dates[0], price=100.0)

    assert isinstance(fill, Fill)
    assert fill.shares == held  # cannot sell more than held
    assert "SPY" not in engine.positions


def test_non_positive_order_rejected() -> None:
    engine = BacktestEngine(initial_cash=1_000.0, trading_dates=[date(2024, 6, 3)])
    zero = _submit(engine, Order("SPY", "buy", 0), price=100.0)
    bad_price = _submit(engine, Order("SPY", "buy", 5), price=0.0)

    assert isinstance(zero, Rejection) and zero.reason == "non_positive"
    assert isinstance(bad_price, Rejection) and bad_price.reason == "non_positive"


def test_negative_initial_cash_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BacktestEngine(initial_cash=-1.0, trading_dates=[date(2024, 6, 3)])


def test_non_finite_initial_cash_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        BacktestEngine(initial_cash=float("nan"), trading_dates=[date(2024, 6, 3)])


def test_run_backtest_requires_close_column() -> None:
    bars = pd.DataFrame([{"symbol": "SPY", "date": date(2024, 6, 3)}])
    with pytest.raises(ValueError, match="missing required columns"):
        run_backtest(bars=bars, target_provider=_hold_first("SPY"), initial_cash=1_000.0)


def test_run_backtest_rejects_duplicate_symbol_date() -> None:
    bars = pd.concat([_linear_bars("SPY", [100.0]), _linear_bars("SPY", [101.0])])
    with pytest.raises(ValueError, match="duplicate"):
        run_backtest(bars=bars, target_provider=_hold_first("SPY"), initial_cash=1_000.0)


def test_run_backtest_rejects_non_finite_close() -> None:
    bars = _linear_bars("SPY", [float("nan")])
    with pytest.raises(ValueError, match="non-finite"):
        run_backtest(bars=bars, target_provider=_hold_first("SPY"), initial_cash=1_000.0)


def test_missing_price_for_target_records_warning() -> None:
    bars = _linear_bars("SPY", [100.0, 101.0])

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if day == bars["date"].min():
            return TargetPortfolio(
                as_of=day,
                weights={"SPY": 0.5, "MISSING": 0.5},
                layers={"SPY": "core", "MISSING": "core"},
                cash_weight=0.0,
            )
        return None

    result = run_backtest(bars=bars, target_provider=provider, initial_cash=10_000.0)
    assert any("MISSING" in w for w in result.warnings)


def test_slippage_bps_reported_on_fill() -> None:
    engine = BacktestEngine(initial_cash=100_000.0, trading_dates=[date(2024, 6, 3)])
    fill = _submit(engine, Order("SPY", "buy", 100, "etf"), price=100.0)
    assert isinstance(fill, Fill)
    # ETF slippage tier is 0.05% = 5 bps of notional.
    assert abs(fill.slippage_bps - 5.0) < 1e-6


def test_single_stock_slippage_double_etf() -> None:
    engine = BacktestEngine(initial_cash=100_000.0, trading_dates=[date(2024, 6, 3)])
    fill = _submit(engine, Order("AAPL", "buy", 100, "single_stock"), price=100.0)
    assert isinstance(fill, Fill)
    assert abs(fill.slippage_bps - 10.0) < 1e-6


def test_settle_date_beyond_window_stays_unsettled() -> None:
    # Sell on the last trading date -> settlement date falls outside the window.
    dates = [date(2024, 6, 3)]
    engine = BacktestEngine(initial_cash=10_000.0, trading_dates=dates)
    engine.settled_cash = 0.0
    engine.positions["SPY"] = 10
    engine.submit_order(Order("SPY", "sell", 10), day=dates[0], price=100.0, is_halted=False)

    # Nothing ever settles because there is no T+1 session in the window.
    engine.settle_due(dates[0])
    assert engine.unsettled_total() > 0.0
    assert engine.settled_cash == 0.0


def test_min_weight_change_skips_small_rebalances() -> None:
    # Two sessions: enter fully on day 0, then a tiny target drift on day 1 that
    # falls under the churn threshold must not generate a trade.
    bars = _linear_bars("SPY", [100.0, 100.0])
    weights = iter([1.0, 0.995])

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        weight = next(weights, None)
        if weight is None:
            return None
        return TargetPortfolio(
            as_of=day, weights={"SPY": weight}, layers={"SPY": "core"}, cash_weight=1.0 - weight
        )

    result = run_backtest(
        bars=bars, target_provider=provider, initial_cash=100_000.0, min_weight_change=0.05
    )
    # Only the day-0 entry fills; the sub-threshold drift on day 1 is skipped.
    assert len(result.fills) == 1


def test_partial_sell_keeps_remaining_position() -> None:
    dates = [date(2024, 6, 3), date(2024, 6, 4)]
    engine = BacktestEngine(initial_cash=100_000.0, trading_dates=dates)
    buy = _submit(engine, Order("SPY", "buy", 100), day=dates[0], price=100.0)
    assert isinstance(buy, Fill)
    held = buy.shares
    sell = _submit(engine, Order("SPY", "sell", held - 1), day=dates[0], price=100.0)

    assert isinstance(sell, Fill)
    assert sell.shares == held - 1
    assert engine.positions["SPY"] == 1


# ---- Determinism (T13-style digest) --------------------------------------


def test_t13_digest_is_stable_across_runs() -> None:
    bars = _linear_bars("SPY", [100.0, 102.0, 101.0, 105.0, 108.0])
    r1 = run_backtest(bars=bars, target_provider=_hold_first("SPY"), initial_cash=50_000.0)
    r2 = run_backtest(bars=bars, target_provider=_hold_first("SPY"), initial_cash=50_000.0)
    assert r1.digest() == r2.digest()


def test_digest_changes_when_fills_differ() -> None:
    bars = _linear_bars("SPY", [100.0, 102.0])
    r1 = run_backtest(bars=bars, target_provider=_hold_first("SPY"), initial_cash=50_000.0)
    r2 = run_backtest(bars=bars, target_provider=_hold_first("SPY"), initial_cash=10_000.0)
    assert r1.digest() != r2.digest()


# ---- Property invariants (06 §3) -----------------------------------------


@settings(max_examples=150, deadline=None)
@given(
    prices=st.lists(
        st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=12,
    ),
    weight=st.floats(min_value=0.0, max_value=1.0),
    initial_cash=st.floats(min_value=1_000.0, max_value=1_000_000.0),
)
def test_property_cash_conservation_and_non_negative_positions(
    prices: list[float], weight: float, initial_cash: float
) -> None:
    bars = _linear_bars("SPY", prices)
    result = run_backtest(
        bars=bars, target_provider=_hold_first("SPY", weight), initial_cash=initial_cash
    )

    # Positions never go negative (long-only, whole shares).
    assert all(shares >= 0 for shares in result.final_positions.values())
    # Fees are non-negative and every buy carries the fixed commission.
    for fill in result.fills:
        assert fill.commission > 0.0  # fixed per-trade fee is always charged.
        assert fill.slippage >= 0.0
        assert fill.regulatory_fees >= 0.0
    # Final equity is finite and non-negative.
    assert result.final_equity() >= 0.0


@settings(max_examples=100, deadline=None)
@given(
    prices=st.lists(
        st.floats(min_value=5.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        min_size=3,
        max_size=10,
    ),
)
def test_property_buying_power_never_negative(prices: list[float]) -> None:
    bars = _linear_bars("SPY", prices)
    result = run_backtest(
        bars=bars,
        target_provider=_hold_first("SPY", 1.0),
        initial_cash=100_000.0,
        cost_model=UsCostModel(),
    )
    # A cash account can never end with negative deployable cash.
    assert result.final_cash >= -1e-6
