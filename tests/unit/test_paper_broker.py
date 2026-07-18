"""Unit tests for the PaperBroker, T7 parity and execution-quality backfill (WP9)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta

import pandas as pd
import pytest

from yquant.backtest.costs import UsCostModel
from yquant.backtest.engine import BacktestResult, EquityPoint, TargetProvider, run_backtest
from yquant.paper.broker import (
    DEFAULT_PAPER_CASH,
    PaperBroker,
    PaperConfig,
    build_paper_result,
    run_paper,
)
from yquant.paper.execution import (
    IntendedTrade,
    SessionBar,
    backfill_execution_quality,
    realized_fill,
)
from yquant.paper.parity import compare_curves, parity_report, shadow_reconciliation
from yquant.strategies.base import TargetPortfolio


def _bars(closes: dict[str, list[float]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2024, 1, 2)
    for symbol, series in closes.items():
        for offset, close in enumerate(series):
            price = round(close, 4)
            rows.append(
                {
                    "symbol": symbol,
                    "date": start + timedelta(days=offset),
                    "low": round(price * 0.98, 4),
                    "high": round(price * 1.02, 4),
                    "close": price,
                    "is_halted": False,
                }
            )
    return pd.DataFrame(rows)


def _provider_factory() -> Callable[[], TargetProvider]:
    def factory() -> TargetProvider:
        placed = {"done": False}

        def provider(day: date, prices: Mapping[str, float]) -> TargetPortfolio | None:
            if placed["done"] or not prices:
                return None
            placed["done"] = True
            return TargetPortfolio(
                as_of=day,
                weights={"SPY": 0.5, "TLT": 0.3},
                layers={"SPY": "core", "TLT": "core"},
                cash_weight=0.2,
            )

        return provider

    return factory


def test_default_paper_cash_is_fifty_thousand() -> None:
    assert DEFAULT_PAPER_CASH == 50_000.0
    assert PaperConfig().initial_cash == 50_000.0


def test_paper_and_backtest_agree_bit_for_bit() -> None:
    bars = _bars({"SPY": [100, 101, 102, 103, 104], "TLT": [90, 89, 91, 90, 92]})
    factory = _provider_factory()

    backtest = run_backtest(
        bars=bars, target_provider=factory(), initial_cash=50_000.0
    )
    paper = build_paper_result(bars=bars, target_provider=factory())

    # Structural T7 parity: identical constraint core -> identical digest.
    assert paper.digest() == backtest.digest()
    assert paper.final_positions == backtest.final_positions
    assert paper.final_cash == pytest.approx(backtest.final_cash)


def test_parity_report_is_zero_bps_and_passes_t7() -> None:
    bars = _bars({"SPY": [100, 102, 101, 103, 105, 104], "TLT": [90, 90, 91, 92, 91, 93]})
    report = parity_report(
        bars=bars, provider_factory=_provider_factory(), initial_cash=50_000.0
    )

    assert report.passed
    assert report.max_daily_bps == 0.0
    assert report.cumulative_bps == 0.0
    assert report.backtest_digest == report.paper_digest
    assert report.sessions == 6


def test_parity_report_rejects_non_callable_factory() -> None:
    bars = _bars({"SPY": [100, 101]})
    with pytest.raises(TypeError):
        parity_report(bars=bars, provider_factory=object(), initial_cash=50_000.0)


def test_parity_config_cash_is_reconciled_to_run_cash() -> None:
    bars = _bars({"SPY": [100, 101, 102], "TLT": [90, 91, 92]})
    # A config with mismatched cash must be coerced to the run's initial_cash.
    cfg = PaperConfig(initial_cash=12_345.0)
    report = parity_report(
        bars=bars, provider_factory=_provider_factory(), initial_cash=50_000.0, config=cfg
    )
    assert report.passed


def test_compare_curves_flags_drift_over_cap() -> None:
    bars = _bars({"SPY": [100, 101, 102], "TLT": [90, 91, 92]})
    factory = _provider_factory()
    backtest = run_backtest(bars=bars, target_provider=factory(), initial_cash=50_000.0)
    paper = build_paper_result(bars=bars, target_provider=factory())
    # Tightening the caps to zero after injecting a synthetic drift trips T7.
    drifted = compare_curves(backtest, paper, daily_cap_bps=-1.0)
    assert not drifted.passed


def test_shadow_report_needs_min_sessions() -> None:
    bars = _bars({"SPY": [100, 101, 102], "TLT": [90, 91, 92]})
    report = shadow_reconciliation(
        bars=bars, provider_factory=_provider_factory(), initial_cash=50_000.0, min_sessions=20
    )
    # Only 3 sessions here: parity is clean but the min-sessions gate fails.
    assert report.parity.passed
    assert not report.meets_min_sessions
    assert not report.passed
    assert report.reconciliation_breaches == 0


def test_shadow_report_rejects_non_callable_factory() -> None:
    bars = _bars({"SPY": [100, 101]})
    with pytest.raises(TypeError):
        shadow_reconciliation(bars=bars, provider_factory=object(), initial_cash=50_000.0)


def test_paper_broker_reconciles_every_session_balanced() -> None:
    bars = _bars({"SPY": [100, 101, 102, 103], "TLT": [90, 91, 92, 93]})
    broker = run_paper(bars=bars, target_provider=_provider_factory()())
    assert len(broker.reconciliations) == 4
    assert all(tick.balanced for tick in broker.reconciliations)
    assert not broker.frozen


def test_frozen_session_bypasses_target_provider() -> None:
    dates = [date(2024, 1, 2), date(2024, 1, 3)]
    broker = PaperBroker(trading_dates=dates, config=PaperConfig(initial_cash=50_000.0))
    # Force the freeze flag as a books-don't-balance breach would.
    broker._frozen = True  # noqa: SLF001

    calls = {"n": 0}

    def provider(day: date, prices: Mapping[str, float]) -> TargetPortfolio | None:
        calls["n"] += 1
        return TargetPortfolio(
            as_of=day, weights={"SPY": 0.5}, layers={"SPY": "core"}, cash_weight=0.5
        )

    broker.on_session(day=dates[0], closes_today={"SPY": 100.0}, target_provider=provider)
    # Frozen: the provider is bypassed, so no order is placed this session.
    assert calls["n"] == 0
    assert broker.result().final_positions == {}


def test_paper_broker_rejects_duplicate_session() -> None:
    day = date(2024, 1, 2)
    broker = PaperBroker(trading_dates=[day])
    provider = _provider_factory()()
    broker.on_session(day=day, closes_today={"SPY": 100.0}, target_provider=provider)

    with pytest.raises(ValueError, match="strictly increasing"):
        broker.on_session(day=day, closes_today={"SPY": 100.0}, target_provider=provider)


def test_realized_fill_applies_adverse_slippage() -> None:
    trade = IntendedTrade(
        day=date(2024, 1, 2), symbol="SPY", side="buy", shares=10, assumed_price=100.0
    )
    fill = realized_fill(trade, SessionBar(open=100.0, low=99.0, high=101.0))
    # ETF slippage is 0.05% = 5 bps adverse on a buy.
    assert fill.filled
    assert fill.realized_price == pytest.approx(100.05)
    assert fill.slippage_bps == pytest.approx(5.0)


def test_realized_fill_clamps_into_traded_range() -> None:
    trade = IntendedTrade(
        day=date(2024, 1, 2), symbol="STK01", side="buy", shares=5,
        assumed_price=100.0, instrument="single_stock",
    )
    # Open slip would land at 101.101 but the high caps it at 101.05.
    fill = realized_fill(trade, SessionBar(open=101.0, low=100.5, high=101.05))
    assert fill.realized_price == pytest.approx(101.05)


def test_realized_fill_sell_slips_down() -> None:
    trade = IntendedTrade(
        day=date(2024, 1, 2), symbol="SPY", side="sell", shares=10, assumed_price=100.0
    )
    fill = realized_fill(trade, SessionBar(open=100.0, low=99.0, high=101.0))
    assert fill.realized_price == pytest.approx(99.95)
    # A lower sell price than assumed is adverse -> positive bps.
    assert fill.slippage_bps == pytest.approx(5.0)


def test_realized_fill_on_halt_does_not_fill() -> None:
    trade = IntendedTrade(
        day=date(2024, 1, 2), symbol="SPY", side="buy", shares=10, assumed_price=100.0
    )
    fill = realized_fill(trade, SessionBar(open=100.0, low=99.0, high=101.0, is_halted=True))
    assert not fill.filled
    assert fill.reason == "halted"


def test_realized_fill_rejects_zero_assumed_price() -> None:
    trade = IntendedTrade(
        day=date(2024, 1, 2), symbol="SPY", side="buy", shares=10, assumed_price=0.0
    )
    with pytest.raises(ValueError, match="assumed_price"):
        realized_fill(trade, SessionBar(open=100.0, low=99.0, high=101.0))


def test_backfill_execution_quality_summarizes_slippage() -> None:
    trades = [
        IntendedTrade(date(2024, 1, 2), "SPY", "buy", 10, 100.0),
        IntendedTrade(date(2024, 1, 3), "TLT", "sell", 5, 90.0),
    ]
    bars = {
        (date(2024, 1, 2), "SPY"): SessionBar(open=100.0, low=99.0, high=101.0),
        (date(2024, 1, 3), "TLT"): SessionBar(open=90.0, low=89.0, high=91.0),
    }
    report = backfill_execution_quality(trades, bars)
    assert report.filled_count == 2
    assert report.halted_count == 0
    assert report.mean_slippage_bps == pytest.approx(5.0)
    assert report.total_slippage_usd == pytest.approx(10 * 0.05 + 5 * 0.045)


def test_backfill_missing_bar_is_treated_as_halted() -> None:
    trades = [IntendedTrade(date(2024, 1, 2), "SPY", "buy", 10, 100.0)]
    report = backfill_execution_quality(trades, {})
    assert report.filled_count == 0
    assert report.halted_count == 1
    assert report.mean_slippage_bps == 0.0
    assert report.worst_slippage_bps == 0.0


def test_custom_cost_model_changes_slippage() -> None:
    trade = IntendedTrade(
        day=date(2024, 1, 2), symbol="SPY", side="buy", shares=10, assumed_price=100.0
    )
    model = UsCostModel.from_rates(
        commission_per_trade=9.5,
        sec_fee_rate=0.0,
        finra_taf_per_share=0.0,
        finra_taf_cap=0.0,
        slippage_rate_etf=0.001,
        slippage_rate_single=0.002,
    )
    fill = realized_fill(trade, SessionBar(open=100.0, low=90.0, high=110.0), model=model)
    assert fill.realized_price == pytest.approx(100.1)
    assert fill.slippage_bps == pytest.approx(10.0)


def _curve(points: list[tuple[date, float]]) -> BacktestResult:
    return BacktestResult(
        equity_curve=[EquityPoint(day=d, equity=e) for d, e in points],
        fills=[],
        rejections=[],
        gfv_count=0,
        final_positions={},
        final_cash=points[-1][1],
        initial_cash=points[0][1],
        warnings=[],
    )


def test_compare_curves_detects_drift_and_records_worst_day() -> None:
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    backtest = _curve([(days[0], 50_000.0), (days[1], 50_000.0), (days[2], 50_000.0)])
    # 3 bps drift on the middle day, 1 bp cumulative on the last day.
    paper = _curve([(days[0], 50_000.0), (days[1], 50_015.0), (days[2], 50_005.0)])
    report = compare_curves(backtest, paper)

    assert report.worst_day == days[1].isoformat()
    assert report.max_daily_bps == pytest.approx(3.0)
    assert report.cumulative_bps == pytest.approx(1.0)
    # 3 bps > 2 bps daily cap -> T7 fails.
    assert not report.passed


def test_compare_curves_rejects_missing_session_even_when_overlap_matches() -> None:
    days = [date(2024, 1, 2), date(2024, 1, 3)]
    backtest = _curve([(days[0], 50_000.0), (days[1], 50_000.0)])
    paper = _curve([(days[0], 50_000.0)])

    assert not compare_curves(backtest, paper).passed


def test_compare_curves_skips_zero_base_equity() -> None:
    days = [date(2024, 1, 2), date(2024, 1, 3)]
    backtest = _curve([(days[0], 0.0), (days[1], 0.0)])
    paper = _curve([(days[0], 0.0), (days[1], 0.0)])
    report = compare_curves(backtest, paper)
    # Zero base is skipped for both daily and cumulative; nothing to compare.
    assert report.max_daily_bps == 0.0
    assert report.cumulative_bps == 0.0


def test_reconcile_tick_and_frozen_property_serialize() -> None:
    bars = _bars({"SPY": [100, 101, 102], "TLT": [90, 91, 92]})
    broker = run_paper(bars=bars, target_provider=_provider_factory()())
    tick = broker.reconciliations[0]
    payload = tick.as_dict()
    assert payload["balanced"] is True
    assert payload["frozen_next_session"] is False
    assert not broker.frozen
