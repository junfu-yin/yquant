"""Drill台账: historical-event replays + a fire drill (06 §5, ADR-36).

The plan mandates, as an L2 exit criterion, a *drill ledger* covering the four
frozen golden windows plus a monthly fire drill (a fabricated severity-5 event /
circuit-breaker). These are **process** checks — do the state machine, alert
ladder and explainability plumbing hang together end-to-end — not performance
claims: every record here is ``contaminated=True`` by construction and must
never be read as a backtest result.

Pure and deterministic: each historical drill walks a synthetic calm→stress
input ramp (scaled by the window's characteristic drift/vol) through the M9
state machine and captures the resulting state trajectory; the fire drill routes
fabricated S1 alerts through the real :class:`~yquant.notify.graded.AlertRouter`
and asserts they escalate to the banner + Feishu channels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from yquant.notify.graded import AlertRouter, GradedAlert
from yquant.qa.golden import GOLDEN_WINDOWS, GoldenWindow, _business_days
from yquant.risk.state_machine import RegimeInputs, replay

# Fabricated fire-drill clock; frozen so the台账 hashes stay stable.
_FIRE_TS = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)


@dataclass(frozen=True)
class DrillRecord:
    """One drill outcome for the台账 (JSON-safe)."""

    key: str
    label: str
    kind: str  # "historical_event" | "fire"
    contaminated: bool
    detail: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "contaminated": self.contaminated,
            "detail": dict(self.detail),
        }


def _stress_ramp_inputs(window: GoldenWindow, steps: int) -> list[RegimeInputs]:
    """A calm→stress input ramp scaled by the window's drift magnitude.

    Walks every pillar observable from a benign level toward a stressed one over
    ``steps`` evaluations, so the machine has to traverse RiskOn→…→Crisis. The
    stress fraction at the end is proportional to the window's (negative) drift,
    so the deeper-drawdown windows push closer to Crisis.
    """

    peak = min(1.0, abs(window.market_drift) / 0.0018)  # 2020 covid drift == full stress
    series: list[RegimeInputs] = []
    for i in range(steps):
        frac = peak * (i / max(1, steps - 1))
        series.append(
            RegimeInputs(
                spy_close=100.0 * (1.0 - 0.15 * frac),
                spy_ma_10m=95.0,  # price falls below its 10m MA as frac rises
                pct_sectors_above_200d=0.8 - 0.7 * frac,
                hy_oas_percentile=0.2 + 0.75 * frac,
                hy_oas_change_3m_bp=-40.0 + 260.0 * frac,
                hyg_lqd_z=0.6 - 2.2 * frac,
                vix_level=13.0 + 42.0 * frac,
                vix_term_inversion_days=int(round(6 * frac)),
                rsp_spy_trend_slope=0.15 - 0.5 * frac,
                pct_above_200d=0.75 - 0.65 * frac,
                nfci=-0.4 + 1.3 * frac,
                nfci_change=-0.1 + 0.6 * frac,
                curve_10y_3m=0.6 - 1.4 * frac,
                usd_change_3m=0.0 + 0.08 * frac,
            )
        )
    return series


def historical_event_drill(window: GoldenWindow, *, max_steps: int = 26) -> DrillRecord:
    """Replay a golden window as a calm→stress ramp and capture the state path."""

    days = _business_days(window.start, window.end)
    steps = min(max_steps, len(days))
    sampled_days = days[:: max(1, len(days) // steps)][:steps]
    inputs = _stress_ramp_inputs(window, len(sampled_days))
    readings = replay(list(zip(sampled_days, inputs, strict=True)))

    trajectory = [
        {"date": d.isoformat(), "state": r.state.value, "composite": round(r.composite, 4)}
        for d, r in readings
    ]
    states = [r.state.value for _, r in readings]
    peak_severity = max(r.state.severity for _, r in readings)
    return DrillRecord(
        key=window.key,
        label=window.label,
        kind="historical_event",
        contaminated=True,
        detail={
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "periods": len(readings),
            "start_state": states[0],
            "end_state": states[-1],
            "peak_severity": peak_severity,
            "distinct_states": sorted(set(states)),
            "trajectory": trajectory,
            "note": "process check only; LLM/committee legs contaminated (06 §5)",
        },
    )


def fire_drill() -> DrillRecord:
    """Fabricate a severity-5 event + circuit-breaker and route them (06 §5).

    Asserts the graded router lifts both to S1 and onto the banner + Feishu
    channels — the monthly proof that the alarm path actually fires.
    """

    router = AlertRouter()
    fake_incident = router.route(
        source="layer_budget_breach",
        title="[DRILL] fabricated severity-5 book imbalance",
        text="drill: books do not balance — this is a fire drill, not a real breach",
        ts=_FIRE_TS,
    )
    fake_breaker = router.route(
        source="regime_change_crisis",
        title="[DRILL] fabricated Crisis circuit-breaker",
        text="drill: forcing Crisis entry to exercise the breaker",
        ts=_FIRE_TS,
    )
    assert fake_incident is not None and fake_breaker is not None
    alerts: list[GradedAlert] = [fake_incident, fake_breaker]
    for alert in alerts:
        assert alert.severity == "S1"
        assert set(("banner", "feishu")) <= set(alert.channels)
    return DrillRecord(
        key="fire_drill",
        label="monthly fire drill: fabricated severity-5 + circuit-breaker",
        kind="fire",
        contaminated=True,
        detail={
            "alerts": [
                {
                    "source": a.source,
                    "severity": a.severity,
                    "channels": list(a.channels),
                    "runbook": a.runbook,
                }
                for a in alerts
            ],
            "note": "fabricated events; no real book or regime was affected",
        },
    )


def build_drill_ledger() -> list[DrillRecord]:
    """The full台账: the four historical-event drills plus the fire drill."""

    records = [historical_event_drill(window) for window in GOLDEN_WINDOWS]
    records.append(fire_drill())
    return records
