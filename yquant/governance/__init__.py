"""Model governance: offline evaluation, contamination gating, black-box panel.

WP10 (09 篇) lands the governance machinery around the provider abstraction that
already lives in :mod:`yquant.strategies.base`: the J3 contamination split
(ADR-24), the black-box four-piece characterization bucketed by the M9 state
machine, the non-trading provider evaluation lines, and the JSON-safe panel the
UI renders. Everything here is pure and deterministic — no network, no LLM — so
a governance run reproduces bit-for-bit and can be replayed from the ledger.
"""

from __future__ import annotations

from yquant.governance.blackbox import (
    AttributionPanel,
    BehaviorTest,
    BehaviorTestResult,
    BlackBoxProfile,
    DriftSentinel,
    FeatureDrift,
    PerformanceBucket,
    PerformanceDashboard,
    build_blackbox_profile,
)
from yquant.governance.evaluation import (
    EvalSample,
    OfflineEvaluationReport,
    evaluate_offline,
    split_on_cutoff,
)
from yquant.governance.panel import (
    ModelGovernancePanel,
    ProviderGovernanceRow,
    build_governance_panel,
)
from yquant.governance.thesis_recall import (
    ThesisRecallReport,
    ThesisRecallSample,
    build_thesis_recall_set,
    evaluate_thesis_recall,
)

__all__ = [
    "AttributionPanel",
    "BehaviorTest",
    "BehaviorTestResult",
    "BlackBoxProfile",
    "DriftSentinel",
    "EvalSample",
    "FeatureDrift",
    "ModelGovernancePanel",
    "OfflineEvaluationReport",
    "PerformanceBucket",
    "PerformanceDashboard",
    "ProviderGovernanceRow",
    "ThesisRecallReport",
    "ThesisRecallSample",
    "build_blackbox_profile",
    "build_governance_panel",
    "build_thesis_recall_set",
    "evaluate_offline",
    "evaluate_thesis_recall",
    "split_on_cutoff",
]
