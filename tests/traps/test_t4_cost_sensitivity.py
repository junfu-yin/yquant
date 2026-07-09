"""T4 cost sensitivity (06 §2): the 0/1x/2x cost report is always generated."""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, cast

import pandas as pd

from yquant.backtest import build_report
from yquant.backtest.engine import TargetProvider
from yquant.strategies.base import TargetPortfolio


def _bars() -> pd.DataFrame:
    day = date(2024, 1, 2)
    rows = []
    for i in range(6):
        rows.append({"symbol": "SPY", "date": day, "close": 100.0 + i, "is_halted": False})
        rows.append({"symbol": "QQQ", "date": day, "close": 200.0 + i, "is_halted": False})
        day = day + timedelta(days=20)
    return pd.DataFrame(rows)


def _provider(bars: pd.DataFrame) -> TargetProvider:
    first = bars["date"].min()

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if day == first:
            return TargetPortfolio(
                as_of=day,
                weights={"SPY": 0.5, "QQQ": 0.5},
                layers={"SPY": "core", "QQQ": "core"},
                cash_weight=0.0,
            )
        return None

    return provider


def test_t4_three_cost_tiers_are_present_and_ordered() -> None:
    bars = _bars()
    report = build_report(
        bars=bars, target_provider=_provider(bars), initial_cash=100_000.0
    )

    tiers = cast(list[dict[str, Any]], report["cost_sensitivity"])
    labels = [row["tier"] for row in tiers]
    assert labels == ["0x", "1x", "2x"]

    finals = [row["metrics"]["final_equity"] for row in tiers]
    # Higher cost multiplier can only lower final equity (monotone non-increasing).
    assert finals[0] >= finals[1] >= finals[2]
    # 0x really is costless; 1x and 2x pay strictly more here (there are fills).
    assert finals[0] > finals[2]


def test_t4_report_carries_all_mandatory_fields() -> None:
    bars = _bars()
    report = build_report(
        bars=bars, target_provider=_provider(bars), initial_cash=100_000.0
    )

    for key in (
        "strategy",
        "benchmark",
        "cost_sensitivity",
        "walk_forward",
        "parameter_sensitivity",
        "warnings",
        "rejections",
    ):
        assert key in report, f"missing mandatory report field: {key}"

    assert report["benchmark"] is not None
    assert cast(dict[str, Any], report["benchmark"])["symbol"] == "SPY"
