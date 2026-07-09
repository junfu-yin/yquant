"""T6 settlement (06 §2): T+1 cash settlement, GFV on unsettled re-buys.

Two invariants:
* buying with not-yet-settled sell proceeds is flagged as a Good-Faith
  Violation (counted, never blocked); and
* there is *no* same-day sell ban — a position bought this session can be sold
  the same session and must fill.
"""

from datetime import date

from yquant.backtest import BacktestEngine, Order
from yquant.backtest.engine import Fill


def _dates() -> list[date]:
    return [date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5)]


def test_t6_same_day_round_trip_fills() -> None:
    """Buy then sell in the same session — both must fill (no same-day ban)."""

    dates = _dates()
    engine = BacktestEngine(initial_cash=10_000.0, trading_dates=dates)

    buy = engine.submit_order(Order("SPY", "buy", 50), day=dates[0], price=100.0, is_halted=False)
    sell = engine.submit_order(Order("SPY", "sell", 50), day=dates[0], price=101.0, is_halted=False)

    assert isinstance(buy, Fill)
    assert isinstance(sell, Fill)
    assert engine.positions == {}  # fully flat after the round trip.
    # Proceeds are unsettled the day they are earned.
    assert engine.unsettled_total() > 0.0


def test_t6_buying_with_unsettled_funds_flags_gfv() -> None:
    dates = _dates()
    # Small initial cash: after the first buy, settled cash is tiny, so the
    # re-buy has to lean on unsettled sell proceeds -> GFV.
    engine = BacktestEngine(initial_cash=6_000.0, trading_dates=dates)
    engine.submit_order(Order("SPY", "buy", 50), day=dates[0], price=100.0, is_halted=False)
    engine.submit_order(Order("SPY", "sell", 50), day=dates[0], price=101.0, is_halted=False)

    assert engine.gfv_count == 0  # nothing bought on unsettled funds yet.
    rebuy = engine.submit_order(
        Order("SPY", "buy", 30), day=dates[0], price=101.0, is_halted=False
    )

    assert isinstance(rebuy, Fill)
    assert rebuy.used_unsettled_funds is True
    assert engine.gfv_count == 1


def test_t6_proceeds_settle_on_t_plus_one() -> None:
    dates = _dates()
    engine = BacktestEngine(initial_cash=10_000.0, trading_dates=dates)
    engine.submit_order(Order("SPY", "buy", 50), day=dates[0], price=100.0, is_halted=False)
    engine.submit_order(Order("SPY", "sell", 50), day=dates[0], price=101.0, is_halted=False)

    unsettled_before = engine.unsettled_total()
    assert unsettled_before > 0.0

    # Same day: nothing settles yet.
    engine.settle_due(dates[0])
    assert engine.unsettled_total() == unsettled_before

    # T+1 (2024 is past the T+1 switchover): proceeds settle into cash.
    engine.settle_due(dates[1])
    assert engine.unsettled_total() == 0.0
