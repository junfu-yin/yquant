"""Unit tests for the M2 backtest report builder."""

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from yquant.backtest import build_report, run_backtest
from yquant.backtest.costs import UsCostModel
from yquant.backtest.engine import TargetProvider
from yquant.backtest.report import (
    annualized_return,
    metrics_of,
    scale_cost_model,
)
from yquant.strategies.base import TargetPortfolio


def _bars(symbols: tuple[str, ...], n: int = 8) -> pd.DataFrame:
    day = date(2024, 1, 2)
    rows = []
    for i in range(n):
        for j, sym in enumerate(symbols):
            rows.append(
                {"symbol": sym, "date": day, "close": 100.0 + i + j * 10, "is_halted": False}
            )
        day = day + timedelta(days=30)
    return pd.DataFrame(rows)


def _hold_first(weights: dict[str, float]) -> TargetProvider:
    placed = {"done": False}

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if placed["done"]:
            return None
        placed["done"] = True
        return TargetPortfolio(
            as_of=day,
            weights=dict(weights),
            layers=dict.fromkeys(weights, "core"),
            cash_weight=0.0,
        )

    return provider


def test_scale_cost_model_zeroes_all_components() -> None:
    model = UsCostModel()
    zero = scale_cost_model(model, Decimal("0"))
    assert zero.commission_per_trade == Decimal("0")
    assert zero.sec_fee_rate == Decimal("0")
    assert zero.finra_taf_per_share == Decimal("0")
    assert zero.slippage_rate_etf == Decimal("0")
    assert zero.slippage_rate_single == Decimal("0")


def test_scale_cost_model_doubles_all_components() -> None:
    model = UsCostModel()
    doubled = scale_cost_model(model, Decimal("2"))
    assert doubled.commission_per_trade == model.commission_per_trade * 2
    assert doubled.slippage_rate_single == model.slippage_rate_single * 2


def test_annualized_return_positive_for_growth() -> None:
    bars = _bars(("SPY",), n=13)  # ~1 year of monthly bars
    result = run_backtest(
        bars=bars, target_provider=_hold_first({"SPY": 1.0}), initial_cash=100_000.0
    )
    ann = annualized_return(result)
    assert ann > 0.0


def test_annualized_return_falls_back_without_span() -> None:
    bars = _bars(("SPY",), n=1)
    result = run_backtest(
        bars=bars, target_provider=_hold_first({"SPY": 1.0}), initial_cash=100_000.0
    )
    # Single point -> no span, falls back to total return.
    assert annualized_return(result) == result.total_return()


def test_metrics_of_reports_curve_bounds() -> None:
    bars = _bars(("SPY",))
    result = run_backtest(
        bars=bars, target_provider=_hold_first({"SPY": 1.0}), initial_cash=100_000.0
    )
    metrics = metrics_of(result)
    assert metrics.start == result.equity_curve[0].day
    assert metrics.end == result.equity_curve[-1].day
    assert metrics.num_fills == len(result.fills)


def test_build_report_has_all_sections_and_ordered_tiers() -> None:
    bars = _bars(("SPY", "QQQ"))
    report = build_report(
        bars=bars, target_provider=_hold_first({"SPY": 0.6, "QQQ": 0.4}), initial_cash=100_000.0
    )

    assert set(report) == {
        "strategy",
        "benchmark",
        "cost_sensitivity",
        "walk_forward",
        "parameter_sensitivity",
        "warnings",
        "rejections",
    }
    tiers = [row["tier"] for row in cast(list[dict[str, Any]], report["cost_sensitivity"])]
    assert tiers == ["0x", "1x", "2x"]
    finals = [
        row["metrics"]["final_equity"]
        for row in cast(list[dict[str, Any]], report["cost_sensitivity"])
    ]
    assert finals[0] >= finals[1] >= finals[2]


def test_build_report_warns_when_benchmark_absent() -> None:
    bars = _bars(("QQQ",))  # no SPY
    report = build_report(
        bars=bars, target_provider=_hold_first({"QQQ": 1.0}), initial_cash=100_000.0
    )
    assert report["benchmark"] is None
    assert any("SPY" in w for w in cast(list[str], report["warnings"]))


def test_build_report_is_json_serialisable() -> None:
    import json

    bars = _bars(("SPY", "QQQ"))
    report = build_report(
        bars=bars, target_provider=_hold_first({"SPY": 0.6, "QQQ": 0.4}), initial_cash=100_000.0
    )
    # Round-trips cleanly -> safe for the ledger/UI.
    assert json.loads(json.dumps(report)) == report
