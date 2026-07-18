"""Black-box characterization four-piece set (09 §3, ◆ M9-bucketed).

The doctrine's running-time characterization of any black-box provider is four
panels:

1. **Performance dashboard** — rolling hit-rate / mean-error, bucketed by the
   *M9 four-state* regime (RiskOn / Neutral / RiskOff / Crisis), replacing the
   old ad-hoc moving-average / vol-quantile buckets (09 §3 ◆). Answers "in which
   weather does it work?"
2. **Attribution panel** — top feature contributions, permanently tagged
   "descriptive, not causal" (09 §3-2). It explains what the model weighs, not
   why the world is so.
3. **Drift sentinel** — per-feature PSI with the 0.2 warn / 0.3 freeze ladder,
   plus a single-inference OOD gate that forces ``abstain`` when tripped.
4. **Behavior tests** — golden regression + invariance + directional-expectation
   checks (the financial CheckList); they run in CI at gate level.

Everything is pure and JSON-safe.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from yquant.risk.state_machine import RegimeState

# PSI ladder thresholds (09 §3-3): warn at 0.2, freeze-candidate at 0.3.
PSI_WARN = 0.2
PSI_FREEZE = 0.3

# Regime buckets are the M9 four states, in canonical risk order.
REGIME_BUCKETS: tuple[RegimeState, ...] = (
    RegimeState.RISK_ON,
    RegimeState.NEUTRAL,
    RegimeState.RISK_OFF,
    RegimeState.CRISIS,
)


@dataclass(frozen=True)
class PerformanceBucket:
    """Rolling performance in one M9 regime bucket."""

    regime: RegimeState
    count: int
    hit_rate: float
    mean_abs_error: float

    def as_dict(self) -> dict[str, object]:
        return {
            "regime": self.regime.value,
            "count": self.count,
            "hit_rate": round(self.hit_rate, 4),
            "mean_abs_error": round(self.mean_abs_error, 4),
        }


@dataclass(frozen=True)
class PerformanceDashboard:
    """Piece 1: performance bucketed by the M9 four-state machine (09 §3 ◆)."""

    buckets: tuple[PerformanceBucket, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "regime_buckets": [b.as_dict() for b in self.buckets],
            "bucketing": "M9 four-state machine",
        }


@dataclass(frozen=True)
class AttributionPanel:
    """Piece 2: top feature contributions with the mandatory non-causal caveat."""

    top_features: tuple[tuple[str, float], ...]
    caveat: str = "descriptive attribution, not causal explanation (09 §3-2)"

    def as_dict(self) -> dict[str, object]:
        return {
            "top_features": [
                {"feature": name, "contribution": round(value, 6)}
                for name, value in self.top_features
            ],
            "caveat": self.caveat,
        }


@dataclass(frozen=True)
class FeatureDrift:
    """One feature's PSI reading against its training distribution."""

    feature: str
    psi: float

    def __post_init__(self) -> None:
        if not self.feature.strip():
            raise ValueError("feature must not be empty")
        if not math.isfinite(self.psi) or self.psi < 0:
            raise ValueError("psi must be finite and non-negative")

    @property
    def status(self) -> str:
        if self.psi >= PSI_FREEZE:
            return "freeze_candidate"
        if self.psi >= PSI_WARN:
            return "warn"
        return "ok"

    def as_dict(self) -> dict[str, object]:
        return {"feature": self.feature, "psi": round(self.psi, 4), "status": self.status}


@dataclass(frozen=True)
class DriftSentinel:
    """Piece 3: per-feature PSI ladder + a single-inference OOD abstain gate."""

    feature_drifts: tuple[FeatureDrift, ...]
    ood_threshold: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.ood_threshold) or self.ood_threshold < 0:
            raise ValueError("ood_threshold must be finite and non-negative")

    @property
    def worst_status(self) -> str:
        order = {"ok": 0, "warn": 1, "freeze_candidate": 2}
        worst = "ok"
        for fd in self.feature_drifts:
            if order[fd.status] > order[worst]:
                worst = fd.status
        return worst

    def forces_abstain(self, inference_ood_score: float) -> bool:
        """A per-inference OOD score above the threshold forces ``abstain`` (09 §3-3)."""

        return (
            not math.isfinite(inference_ood_score)
            or inference_ood_score < 0
            or inference_ood_score > self.ood_threshold
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_drifts": [fd.as_dict() for fd in self.feature_drifts],
            "ood_threshold": round(self.ood_threshold, 4),
            "worst_status": self.worst_status,
        }


@dataclass(frozen=True)
class BehaviorTest:
    """One financial-CheckList behavior test case (09 §3-4)."""

    test_id: str
    kind: str  # "golden" | "invariance" | "directional"
    description: str
    predicate: Callable[[], bool]


@dataclass(frozen=True)
class BehaviorTestResult:
    """Outcome of one behavior test."""

    test_id: str
    kind: str
    description: str
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "kind": self.kind,
            "description": self.description,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class BlackBoxProfile:
    """The four-piece characterization set for one provider (09 §3)."""

    provider_id: str
    performance: PerformanceDashboard
    attribution: AttributionPanel
    drift: DriftSentinel
    behavior: tuple[BehaviorTestResult, ...]

    @property
    def behavior_all_green(self) -> bool:
        return all(r.passed for r in self.behavior)

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "performance": self.performance.as_dict(),
            "attribution": self.attribution.as_dict(),
            "drift": self.drift.as_dict(),
            "behavior": [r.as_dict() for r in self.behavior],
            "behavior_all_green": self.behavior_all_green,
        }


@dataclass(frozen=True)
class BucketObservation:
    """One scored observation tagged with the M9 regime it occurred in."""

    regime: RegimeState
    predicted: float
    realized: float


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _build_dashboard(observations: Sequence[BucketObservation]) -> PerformanceDashboard:
    buckets: list[PerformanceBucket] = []
    for regime in REGIME_BUCKETS:
        rows = [o for o in observations if o.regime == regime]
        if not rows:
            buckets.append(
                PerformanceBucket(regime=regime, count=0, hit_rate=0.0, mean_abs_error=0.0)
            )
            continue
        hits = sum(1 for o in rows if _sign(o.predicted) == _sign(o.realized))
        abs_err = sum(abs(o.predicted - o.realized) for o in rows)
        n = len(rows)
        buckets.append(
            PerformanceBucket(
                regime=regime,
                count=n,
                hit_rate=hits / n,
                mean_abs_error=abs_err / n,
            )
        )
    return PerformanceDashboard(buckets=tuple(buckets))


def population_stability_index(
    expected: Sequence[float],
    actual: Sequence[float],
) -> float:
    """PSI of ``actual`` vs ``expected`` distributions over shared deciles.

    Buckets are the deciles of the pooled sample; empty buckets are floored to a
    small epsilon so the log ratio stays finite. Standard drift statistic.
    """

    if not expected or not actual:
        raise ValueError("both distributions must be non-empty")
    if not all(math.isfinite(value) for value in (*expected, *actual)):
        raise ValueError("PSI distributions must contain only finite values")
    pooled = sorted([*expected, *actual])
    n_edges = 10
    edges = [
        pooled[min(len(pooled) - 1, int(round(i / n_edges * (len(pooled) - 1))))]
        for i in range(1, n_edges)
    ]

    def _hist(values: Sequence[float]) -> list[float]:
        counts = [0] * (len(edges) + 1)
        for v in values:
            idx = 0
            while idx < len(edges) and v > edges[idx]:
                idx += 1
            counts[idx] += 1
        total = len(values)
        return [max(c / total, 1e-6) for c in counts]

    exp_hist = _hist(expected)
    act_hist = _hist(actual)
    return sum((a - e) * math.log(a / e) for e, a in zip(exp_hist, act_hist, strict=True))


def build_blackbox_profile(
    provider_id: str,
    *,
    observations: Sequence[BucketObservation],
    top_features: Sequence[tuple[str, float]],
    feature_drifts: Sequence[FeatureDrift],
    ood_threshold: float,
    behavior_tests: Sequence[BehaviorTest] = (),
) -> BlackBoxProfile:
    """Assemble the four-piece characterization for one provider (09 §3).

    Behavior tests are executed here (their predicates are pure) so the profile
    carries pass/fail outcomes the CI gate and the UI can read directly.
    """

    if not provider_id.strip():
        raise ValueError("provider_id must not be empty")
    if not math.isfinite(ood_threshold) or ood_threshold < 0:
        raise ValueError("ood_threshold must be finite and non-negative")
    if any(
        not math.isfinite(value)
        for observation in observations
        for value in (observation.predicted, observation.realized)
    ):
        raise ValueError("observations must contain only finite values")
    if any(not math.isfinite(drift.psi) or drift.psi < 0 for drift in feature_drifts):
        raise ValueError("feature PSI values must be finite and non-negative")
    if any(
        not name.strip() or not math.isfinite(contribution)
        for name, contribution in top_features
    ):
        raise ValueError("feature contributions must have names and finite values")

    dashboard = _build_dashboard(observations)
    attribution = AttributionPanel(
        top_features=tuple(sorted(top_features, key=lambda kv: -abs(kv[1])))
    )
    drift = DriftSentinel(feature_drifts=tuple(feature_drifts), ood_threshold=ood_threshold)
    results = tuple(
        BehaviorTestResult(
            test_id=t.test_id,
            kind=t.kind,
            description=t.description,
            passed=bool(t.predicate()),
        )
        for t in behavior_tests
    )
    return BlackBoxProfile(
        provider_id=provider_id,
        performance=dashboard,
        attribution=attribution,
        drift=drift,
        behavior=results,
    )


__all__ = [
    "PSI_FREEZE",
    "PSI_WARN",
    "REGIME_BUCKETS",
    "AttributionPanel",
    "BehaviorTest",
    "BehaviorTestResult",
    "BlackBoxProfile",
    "BucketObservation",
    "DriftSentinel",
    "FeatureDrift",
    "PerformanceBucket",
    "PerformanceDashboard",
    "build_blackbox_profile",
    "population_stability_index",
]
