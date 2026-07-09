"""Unit tests for the walk-forward OOS validation framework (WP3, 03 §5.3)."""

from collections.abc import Mapping
from datetime import date, timedelta
from typing import cast

import pandas as pd

from yquant.backtest.engine import TargetProvider
from yquant.backtest.walkforward import (
    ProviderFactory,
    parameter_sensitivity,
    rolling_windows,
    run_walk_forward,
    stitch_oos_metrics,
)
from yquant.strategies.base import TargetPortfolio


def _daily_bars(symbols: tuple[str, ...], months: int) -> pd.DataFrame:
    """One bar per ~month for ``months`` months, gently rising."""

    rows = []
    day = date(2018, 1, 2)
    for i in range(months):
        for j, sym in enumerate(symbols):
            rows.append(
                {"symbol": sym, "date": day, "close": 100.0 + i + j * 5, "is_halted": False}
            )
        day = day + timedelta(days=30)
    return pd.DataFrame(rows)


def _hold_first_factory(weights: dict[str, float]) -> ProviderFactory:
    def factory(bars: pd.DataFrame) -> TargetProvider:
        placed = {"done": False}

        def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
            if placed["done"]:
                return None
            if not all(closes.get(s, 0.0) > 0 for s in weights):
                return None
            placed["done"] = True
            return TargetPortfolio(
                as_of=day,
                weights=dict(weights),
                layers={s: "core" for s in weights},
                cash_weight=0.0,
            )

        return provider

    return factory


def test_rolling_windows_are_non_overlapping_oos_by_default() -> None:
    dates = [date(2018, 1, 2) + timedelta(days=30 * i) for i in range(60)]
    windows = rolling_windows(dates, is_months=12, oos_months=12)
    assert windows, "expected at least one window"
    # OOS segments must not overlap.
    for prev, cur in zip(windows, windows[1:], strict=False):
        assert cur[2] > prev[3]
    # IS precedes OOS in every window.
    for is_start, is_end, oos_start, oos_end in windows:
        assert is_start <= is_end < oos_start <= oos_end


def test_rolling_windows_empty_when_history_too_short() -> None:
    dates = [date(2020, 1, 2) + timedelta(days=30 * i) for i in range(6)]
    assert rolling_windows(dates, is_months=12, oos_months=12) == []


def test_run_walk_forward_scores_only_oos_and_is_deterministic() -> None:
    bars = _daily_bars(("SPY",), months=60)
    factory = _hold_first_factory({"SPY": 1.0})
    windows_a = run_walk_forward(
        bars=bars, provider_factory=factory, initial_cash=100_000.0, is_months=12, oos_months=12
    )
    windows_b = run_walk_forward(
        bars=bars, provider_factory=factory, initial_cash=100_000.0, is_months=12, oos_months=12
    )
    assert windows_a, "expected OOS windows"
    # Fully deterministic: identical digests window-for-window.
    assert [w.digest for w in windows_a] == [w.digest for w in windows_b]
    # OOS windows start after their IS window ends.
    for w in windows_a:
        assert w.is_end < w.oos_start


def test_stitch_oos_metrics_reports_percentiles() -> None:
    bars = _daily_bars(("SPY",), months=72)
    windows = run_walk_forward(
        bars=bars,
        provider_factory=_hold_first_factory({"SPY": 1.0}),
        initial_cash=100_000.0,
        is_months=12,
        oos_months=12,
    )
    summary = stitch_oos_metrics(windows)
    assert summary["num_windows"] == len(windows)
    assert "annualized_return_pctile" in summary
    assert set(cast(dict[str, object], summary["annualized_return_pctile"])) == {
        "p10",
        "p50",
        "p90",
    }


def test_stitch_oos_metrics_handles_no_windows() -> None:
    assert stitch_oos_metrics([]) == {"num_windows": 0, "windows": []}


def test_parameter_sensitivity_sweeps_values() -> None:
    bars = _daily_bars(("SPY",), months=12)

    def build(weight: float) -> TargetProvider:
        def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
            if closes.get("SPY", 0.0) <= 0:
                return None
            return TargetPortfolio(
                as_of=day, weights={"SPY": weight}, layers={"SPY": "core"}, cash_weight=1 - weight
            )

        return provider

    rows = parameter_sensitivity(
        bars=bars,
        build_provider=build,
        param_name="spy_weight",
        param_values=[0.5, 1.0],
        initial_cash=100_000.0,
    )
    assert [r["value"] for r in rows] == [0.5, 1.0]
    assert all(r["param"] == "spy_weight" for r in rows)
