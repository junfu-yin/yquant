"""Walk-forward out-of-sample validation (03 §5.3, 02 §样本外优先).

A strategy report's headline conclusion must come from *out-of-sample* results:
the parameters/logic are chosen on an in-sample (IS) window, then evaluated on
the following, never-seen out-of-sample (OOS) window; windows roll forward and
only the stitched OOS segments feed the final verdict (archive 03v2 §walk_forward).

The engine is already a pure function of its bars, so this module just slices
the trading calendar into rolling IS/OOS windows, runs the OOS slice through
:func:`~yquant.backtest.engine.run_backtest`, and stitches per-window metrics
into a JSON-safe payload for :func:`~yquant.backtest.report.build_report`'s
``walk_forward`` seam. No wall-clock reads, so the split is deterministic.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

import pandas as pd

from yquant.backtest.costs import Instrument, UsCostModel
from yquant.backtest.engine import BacktestResult, TargetProvider, run_backtest
from yquant.backtest.report import PerformanceMetrics, metrics_of

# A provider factory closes over the bars it may pre-scan (e.g. resample), so the
# walk-forward driver can build a fresh provider per OOS window.
ProviderFactory = Callable[[pd.DataFrame], TargetProvider]


@dataclass(frozen=True)
class WalkForwardWindow:
    """One IS/OOS split and the OOS backtest metrics."""

    index: int
    is_start: date
    is_end: date
    oos_start: date
    oos_end: date
    metrics: PerformanceMetrics
    digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "is_start": self.is_start.isoformat(),
            "is_end": self.is_end.isoformat(),
            "oos_start": self.oos_start.isoformat(),
            "oos_end": self.oos_end.isoformat(),
            "metrics": self.metrics.as_dict(),
            "digest": self.digest,
        }


def _month_starts(trading_dates: list[date]) -> list[date]:
    """First trading date of each calendar month, ordered."""

    seen: dict[tuple[int, int], date] = {}
    for day in trading_dates:
        key = (day.year, day.month)
        if key not in seen:
            seen[key] = day
    return [seen[key] for key in sorted(seen)]


def rolling_windows(
    trading_dates: list[date],
    *,
    is_months: int,
    oos_months: int,
    step_months: int | None = None,
) -> list[tuple[date, date, date, date]]:
    """Split a calendar into rolling (is_start, is_end, oos_start, oos_end) windows.

    Windows are anchored on calendar-month boundaries and roll forward by
    ``step_months`` (defaults to ``oos_months`` for non-overlapping OOS segments).
    A trailing window with a short OOS tail is kept so the last data is scored.
    """

    if is_months <= 0 or oos_months <= 0:
        raise ValueError("is_months and oos_months must be positive")
    step = step_months if step_months is not None else oos_months
    if step <= 0:
        raise ValueError("step_months must be positive")

    starts = _month_starts(sorted(set(trading_dates)))
    if not starts:
        return []
    last_day = max(trading_dates)

    windows: list[tuple[date, date, date, date]] = []
    cursor = 0
    while cursor + is_months < len(starts):
        is_start = starts[cursor]
        oos_anchor = cursor + is_months
        oos_start = starts[oos_anchor]
        is_end = _prev_day(oos_start)
        oos_end_anchor = oos_anchor + oos_months
        oos_end = _prev_day(starts[oos_end_anchor]) if oos_end_anchor < len(starts) else last_day
        windows.append((is_start, is_end, oos_start, oos_end))
        if oos_end >= last_day:
            break
        cursor += step
    return windows


def _prev_day(day: date) -> date:
    return date.fromordinal(day.toordinal() - 1)


def _slice_bars(bars: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    days = pd.to_datetime(bars["date"]).dt.date
    return bars.loc[(days >= start) & (days <= end)].copy()


def run_walk_forward(
    *,
    bars: pd.DataFrame,
    provider_factory: ProviderFactory,
    initial_cash: float,
    is_months: int = 36,
    oos_months: int = 12,
    step_months: int | None = None,
    cost_model: UsCostModel | None = None,
    instruments: Mapping[str, Instrument] | None = None,
    min_weight_change: float = 0.0,
) -> list[WalkForwardWindow]:
    """Run rolling IS/OOS windows and return the per-window OOS metrics.

    ``provider_factory`` receives the *combined IS+OOS* bars for each window so a
    momentum provider can warm up its history on the IS slice, but the backtest
    only runs over the OOS slice — the IS window shapes state, never the score.
    """

    trading_dates = sorted({d for d in pd.to_datetime(bars["date"]).dt.date})
    if not trading_dates:
        return []

    windows = rolling_windows(
        trading_dates, is_months=is_months, oos_months=oos_months, step_months=step_months
    )
    results: list[WalkForwardWindow] = []
    for index, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
        warmup_bars = _slice_bars(bars, is_start, oos_end)
        oos_bars = _slice_bars(bars, oos_start, oos_end)
        if oos_bars.empty:
            continue
        provider = provider_factory(warmup_bars)
        result = run_backtest(
            bars=oos_bars,
            target_provider=provider,
            initial_cash=initial_cash,
            cost_model=cost_model,
            instruments=instruments,
            min_weight_change=min_weight_change,
        )
        results.append(
            WalkForwardWindow(
                index=index,
                is_start=is_start,
                is_end=is_end,
                oos_start=oos_start,
                oos_end=oos_end,
                metrics=metrics_of(result),
                digest=result.digest(),
            )
        )
    return results


def stitch_oos_metrics(windows: list[WalkForwardWindow]) -> dict[str, object]:
    """Aggregate OOS windows into a headline summary (03 §5.3 honest conclusion).

    Reports the number of windows, the compounded OOS return across windows, and
    the 10/50/90 percentiles of per-window annualised return and max drawdown —
    the honest distribution the interval-book (08) is built from.
    """

    if not windows:
        return {"num_windows": 0, "windows": []}

    compounded = 1.0
    for window in windows:
        compounded *= 1.0 + window.metrics.total_return
    ann = sorted(w.metrics.annualized_return for w in windows)
    mdd = sorted(w.metrics.max_drawdown for w in windows)

    return {
        "num_windows": len(windows),
        "oos_compounded_return": round(compounded - 1.0, 6),
        "annualized_return_pctile": {
            "p10": round(_percentile(ann, 0.10), 6),
            "p50": round(_percentile(ann, 0.50), 6),
            "p90": round(_percentile(ann, 0.90), 6),
        },
        "max_drawdown_pctile": {
            "p10": round(_percentile(mdd, 0.10), 6),
            "p50": round(_percentile(mdd, 0.50), 6),
            "p90": round(_percentile(mdd, 0.90), 6),
        },
        "windows": [w.as_dict() for w in windows],
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile of an already-sorted list."""

    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def parameter_sensitivity(
    *,
    bars: pd.DataFrame,
    build_provider: Callable[[float], TargetProvider],
    param_name: str,
    param_values: list[float],
    initial_cash: float,
    cost_model: UsCostModel | None = None,
    instruments: Mapping[str, Instrument] | None = None,
) -> list[dict[str, object]]:
    """Sweep one parameter and report full-sample metrics per value (02 §敏感性).

    A robust strategy should not be brittle to small parameter changes; this
    fills :func:`build_report`'s ``parameter_sensitivity`` seam.
    """

    rows: list[dict[str, object]] = []
    for value in param_values:
        result: BacktestResult = run_backtest(
            bars=bars,
            target_provider=build_provider(value),
            initial_cash=initial_cash,
            cost_model=cost_model,
            instruments=instruments,
        )
        rows.append({"param": param_name, "value": value, "metrics": metrics_of(result).as_dict()})
    return rows
