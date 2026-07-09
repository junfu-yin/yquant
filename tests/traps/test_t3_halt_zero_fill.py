"""T3' halt (06 §2): an order on a halted day gets zero fill and a rejection."""

from collections.abc import Mapping
from datetime import date

from yquant.backtest import BacktestEngine, Order, run_backtest
from yquant.backtest.engine import Rejection
from yquant.strategies.base import TargetPortfolio


def test_t3_halted_order_rejected_with_zero_fill() -> None:
    engine = BacktestEngine(initial_cash=10_000.0, trading_dates=[date(2024, 6, 3)])
    outcome = engine.submit_order(
        Order("SPY", "buy", 10), day=date(2024, 6, 3), price=100.0, is_halted=True
    )

    assert isinstance(outcome, Rejection)
    assert outcome.reason == "halted"
    assert engine.fills == []
    assert engine.positions == {}
    assert engine.settled_cash == 10_000.0


def test_t3_halt_day_in_run_produces_rejection_not_fill() -> None:
    import pandas as pd

    bars = pd.DataFrame(
        [
            {"symbol": "SPY", "date": date(2024, 6, 3), "close": 100.0, "is_halted": True},
            {"symbol": "SPY", "date": date(2024, 6, 4), "close": 100.0, "is_halted": False},
        ]
    )

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if day == date(2024, 6, 3):
            return TargetPortfolio(
                as_of=day, weights={"SPY": 1.0}, layers={"SPY": "core"}, cash_weight=0.0
            )
        return None

    result = run_backtest(bars=bars, target_provider=provider, initial_cash=10_000.0)

    # The rebalance fired on the halted session, so the order was rejected and
    # never re-attempted (the provider holds on day 4).
    assert result.fills == []
    assert any(r.reason == "halted" for r in result.rejections)
    assert result.final_positions == {}
