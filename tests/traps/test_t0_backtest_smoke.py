"""T0 smoke (06 §2): SPY buy-and-hold backtest ~= index, difference ~= fees."""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, cast

import pandas as pd

from yquant.backtest import build_report, run_backtest
from yquant.backtest.engine import TargetProvider
from yquant.strategies.base import TargetPortfolio


def _spy_bars(closes: list[float]) -> pd.DataFrame:
    day = date(2024, 1, 2)
    rows = []
    for close in closes:
        rows.append({"symbol": "SPY", "date": day, "close": close, "is_halted": False})
        day = day + timedelta(days=1)
    return pd.DataFrame(rows)


def _buy_and_hold(symbol: str) -> TargetProvider:
    placed = {"done": False}

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if placed["done"] or symbol not in closes:
            return None
        placed["done"] = True
        return TargetPortfolio(
            as_of=day, weights={symbol: 1.0}, layers={symbol: "core"}, cash_weight=0.0
        )

    return provider


def test_t0_buy_and_hold_tracks_index_minus_fees() -> None:
    """A +20% index move yields ~+20% equity, dragged only by entry costs."""

    closes = [100.0, 105.0, 110.0, 115.0, 120.0]
    bars = _spy_bars(closes)
    result = run_backtest(
        bars=bars, target_provider=_buy_and_hold("SPY"), initial_cash=100_000.0
    )

    index_return = closes[-1] / closes[0] - 1.0  # +20%
    equity_return = result.total_return()

    # Equity tracks the index but lags slightly because of the entry commission
    # and slippage — it must never exceed the index return.
    assert equity_return < index_return
    assert index_return - equity_return < 0.01  # drag is small (fees only)
    assert result.gfv_count == 0
    assert result.rejections == []


def test_t0_zero_cost_tier_matches_index_exactly_bar_the_rounding() -> None:
    """At 0x cost the only gap to the index is whole-share rounding."""

    closes = [100.0, 120.0]
    bars = _spy_bars(closes)
    report = build_report(
        bars=bars, target_provider=_buy_and_hold("SPY"), initial_cash=100_000.0
    )
    tiers = {
        row["tier"]: row["metrics"]
        for row in cast(list[dict[str, Any]], report["cost_sensitivity"])
    }

    # 1000 shares * 100 = 100000 exactly, so 0x return equals the index move.
    assert abs(tiers["0x"]["total_return"] - 0.20) < 1e-9
    # Fees only reduce return: 0x >= 1x >= 2x.
    assert tiers["0x"]["final_equity"] >= tiers["1x"]["final_equity"]
    assert tiers["1x"]["final_equity"] >= tiers["2x"]["final_equity"]
