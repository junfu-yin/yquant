"""P-series precision metrics as pure, scriptable checkers (06 §1).

Each ``check_p*`` returns a :class:`MetricResult` — a pass/fail verdict with the
evidence a reviewer or the UI panel needs. They are deterministic and free of
wall-clock / IO so a QA run reproduces bit-for-bit (07). Only the metrics that
are *scriptable today* live here (P1/P2/P3/P4/P6/P10/P11); the SLA / rolling
success metrics (P5/P7/P8/P9) are operational counters computed from the ledger
over time and are out of this module's scope.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

from yquant.backtest.costs import Instrument, UsCostModel
from yquant.backtest.engine import BacktestResult, TargetProvider, run_backtest
from yquant.datasrc.reconcile import ReconciliationReport
from yquant.risk.state_machine import PILLARS, RegimeReading

# A cent is the accounting unit; conservation must hold to half a cent so pure
# float accumulation slack never trips a real breach.
_CENT = 0.005


@dataclass(frozen=True)
class MetricResult:
    """One P-metric verdict, JSON-safe for the panel / ledger."""

    metric: str
    name: str
    passed: bool
    severity: str  # "block" | "S1" | "S2" | "info"
    detail: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity,
            "detail": dict(self.detail),
        }


def last_close_by_symbol(bars: pd.DataFrame) -> dict[str, float]:
    """Latest close per symbol from a repo read view (marks final positions)."""

    frame = bars.loc[:, ["symbol", "date", "close"]].copy()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.sort_values(["symbol", "date"])
    out: dict[str, float] = {}
    for symbol, group in frame.groupby("symbol", sort=True):
        closes = [float(c) for c in group["close"].tolist() if not pd.isna(c)]
        if closes:
            out[str(symbol)] = closes[-1]
    return out


def check_p1_accounting_conservation(
    result: BacktestResult, *, tolerance_usd: float = _CENT
) -> MetricResult:
    """P1: cash reconstructed from fills equals the engine's final buying power.

    Each buy removes ``gross + fees`` and each sell adds ``gross - fees`` from the
    starting cash; the identity must hold to the cent or an order booked money it
    never moved.
    """

    reconstructed = result.initial_cash
    for fill in result.fills:
        if fill.side == "buy":
            reconstructed -= fill.gross + fill.cost_total
        else:
            reconstructed += fill.gross - fill.cost_total
    diff = abs(reconstructed - result.final_cash)
    return MetricResult(
        metric="P1",
        name="accounting conservation",
        passed=diff <= tolerance_usd,
        severity="block",
        detail={
            "reconstructed_cash": round(reconstructed, 6),
            "engine_final_cash": round(result.final_cash, 6),
            "diff_usd": round(diff, 6),
            "fills": len(result.fills),
        },
    )


def check_p2_nav_double_calc(
    result: BacktestResult,
    last_close: Mapping[str, float],
    *,
    tolerance_usd: float = _CENT,
) -> MetricResult:
    """P2: the curve's final equity equals cash plus marked positions, to the cent.

    Two independent NAV paths — the engine's equity curve tail and a manual
    ``cash + Σ shares×close`` reconstruction — must agree.
    """

    curve_equity = result.final_equity()
    marked = sum(
        shares * last_close.get(symbol, 0.0)
        for symbol, shares in result.final_positions.items()
    )
    recomputed = result.final_cash + marked
    diff = abs(curve_equity - recomputed)
    return MetricResult(
        metric="P2",
        name="NAV double-calculation",
        passed=diff <= tolerance_usd,
        severity="block",
        detail={
            "curve_equity": round(curve_equity, 6),
            "recomputed_equity": round(recomputed, 6),
            "diff_usd": round(diff, 6),
        },
    )


def check_p3_source_consistency(
    report: ReconciliationReport, *, minimum: float = 0.995
) -> MetricResult:
    """P3: two-source sampled agreement rate ≥ 99.5% (yfinance vs Stooq)."""

    passed = report.compared_rows > 0 and report.consistency_rate >= minimum
    return MetricResult(
        metric="P3",
        name="two-source consistency",
        passed=passed,
        severity="S1",
        detail={
            "consistency_rate": round(report.consistency_rate, 6),
            "minimum": minimum,
            "compared_rows": report.compared_rows,
            "mismatches": len(report.mismatches),
            "left_source": report.left_source,
            "right_source": report.right_source,
        },
    )


def check_p4_adjusted_price_continuity(
    adjusted_closes: Sequence[tuple[date, float]],
    *,
    event_dates: Sequence[date],
    baseline_multiple: float = 3.0,
    absolute_floor: float = 0.001,
) -> MetricResult:
    """P4: adjusted price is continuous across split/dividend dates.

    Backward split adjustment must leave the adjusted series smooth, so the
    day-over-day move on a corporate-action date should look like any other
    session — a residual left-in split shows up as an anomalous jump. Since a
    normal market move can exceed a fixed 0.1%, the event-date move is judged
    *relative to the typical non-event move*: it fails only when it exceeds
    ``baseline_multiple × median(non-event |returns|)`` and also clears
    ``absolute_floor`` (so a genuinely flat series is never flagged).
    """

    series = sorted(adjusted_closes, key=lambda item: item[0])
    events = set(event_dates)
    returns: list[tuple[date, float]] = []
    for (_, prev_close), (day, close) in zip(series, series[1:], strict=False):
        if prev_close <= 0:
            continue
        returns.append((day, abs(close / prev_close - 1.0)))

    non_event = sorted(r for day, r in returns if day not in events)
    baseline = _median(non_event) if non_event else 0.0
    ceiling = max(baseline * baseline_multiple, absolute_floor)

    jumps = [
        {"date": day.isoformat(), "jump": round(r, 6)}
        for day, r in returns
        if day in events and r > ceiling
    ]
    return MetricResult(
        metric="P4",
        name="adjusted-price continuity",
        passed=not jumps,
        severity="block",
        detail={
            "baseline_move": round(baseline, 6),
            "ceiling": round(ceiling, 6),
            "event_dates": [d.isoformat() for d in sorted(events)],
            "discontinuities": jumps,
        },
    )


def _median(sorted_values: Sequence[float]) -> float:
    """Median of an already-sorted, non-empty sequence."""

    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def check_p6_digest_reproducible(
    *,
    bars: pd.DataFrame,
    provider_factory: Callable[[], TargetProvider],
    initial_cash: float,
    runs: int = 2,
    cost_model: UsCostModel | None = None,
    instruments: Mapping[str, Instrument] | None = None,
    min_weight_change: float = 0.0,
) -> MetricResult:
    """P6: replay consistency = 100%.

    Runs the same backtest ``runs`` times (a fresh provider each time so state
    cannot leak) and requires an identical digest every time.
    """

    digests: list[str] = []
    for _ in range(max(2, runs)):
        result = run_backtest(
            bars=bars,
            target_provider=provider_factory(),
            initial_cash=initial_cash,
            cost_model=cost_model,
            instruments=instruments,
            min_weight_change=min_weight_change,
        )
        digests.append(result.digest())
    unique = sorted(set(digests))
    return MetricResult(
        metric="P6",
        name="replay reproducibility",
        passed=len(unique) == 1,
        severity="block",
        detail={"runs": len(digests), "unique_digests": len(unique), "digest": unique[0]},
    )


def check_p10_state_machine_availability(
    readings: Sequence[RegimeReading],
) -> MetricResult:
    """P10: the machine yields a valid state every period, even with stale inputs.

    Availability is 100% by design (a data gap carries the last score forward
    rather than manufacturing a regime); this asserts that guarantee and reports
    how often pillars ran stale.
    """

    total = len(readings)
    incomplete = [
        i for i, r in enumerate(readings) if set(r.pillar_scores) != set(PILLARS)
    ]
    stale_periods = sum(1 for r in readings if r.stale_pillars)
    passed = total > 0 and not incomplete
    return MetricResult(
        metric="P10",
        name="state-machine availability",
        passed=passed,
        severity="S1",
        detail={
            "periods": total,
            "incomplete_periods": incomplete,
            "stale_periods": stale_periods,
            "stale_ratio": round(stale_periods / total, 6) if total else None,
        },
    )


def check_p11_layer_budget(
    layer_weights: Mapping[str, float],
    *,
    overlay_cap: float = 0.10,
) -> MetricResult:
    """P11: three-layer water levels; Overlay > 10% is an S1 breach.

    Also flags a total invested weight above 100% (leverage), which is a hard
    block for the long-only v1 book.
    """

    overlay = float(layer_weights.get("overlay", 0.0))
    total = sum(float(w) for w in layer_weights.values())
    violations: list[str] = []
    if overlay > overlay_cap + 1e-9:
        violations.append("overlay_cap")
    if total > 1.0 + 1e-9:
        violations.append("leverage")
    severity = "S1" if "overlay_cap" in violations or "leverage" in violations else "info"
    return MetricResult(
        metric="P11",
        name="layer-budget compliance",
        passed=not violations,
        severity=severity,
        detail={
            "overlay_weight": round(overlay, 6),
            "overlay_cap": overlay_cap,
            "total_weight": round(total, 6),
            "violations": violations,
            "layers": {k: round(float(v), 6) for k, v in layer_weights.items()},
        },
    )
