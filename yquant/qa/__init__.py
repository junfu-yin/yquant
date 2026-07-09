"""M-QA: scriptable quality gates (06 篇).

Exposes the P-series precision metrics as pure checkers, the frozen golden
dataset (four regression/drill windows), and a panel assembler so CI and the UI
render the same verdicts. Everything here is deterministic and side-effect free
so a QA run is itself replayable (07).
"""

from __future__ import annotations

from yquant.qa.drills import (
    DrillRecord,
    build_drill_ledger,
    fire_drill,
    historical_event_drill,
)
from yquant.qa.golden import (
    GOLDEN_UNIVERSE,
    GOLDEN_WINDOWS,
    GoldenWindow,
    build_golden_bars,
    golden_content_hash,
    golden_manifest,
)
from yquant.qa.metrics import (
    MetricResult,
    check_p1_accounting_conservation,
    check_p2_nav_double_calc,
    check_p3_source_consistency,
    check_p4_adjusted_price_continuity,
    check_p6_digest_reproducible,
    check_p10_state_machine_availability,
    check_p11_layer_budget,
)
from yquant.qa.panel import QaPanel, build_panel

__all__ = [
    "GOLDEN_UNIVERSE",
    "GOLDEN_WINDOWS",
    "DrillRecord",
    "GoldenWindow",
    "MetricResult",
    "QaPanel",
    "build_drill_ledger",
    "build_golden_bars",
    "build_panel",
    "check_p1_accounting_conservation",
    "check_p2_nav_double_calc",
    "check_p3_source_consistency",
    "check_p4_adjusted_price_continuity",
    "check_p6_digest_reproducible",
    "check_p10_state_machine_availability",
    "check_p11_layer_budget",
    "fire_drill",
    "golden_content_hash",
    "golden_manifest",
    "historical_event_drill",
]
