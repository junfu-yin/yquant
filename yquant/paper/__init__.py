"""M-live PaperBroker + shadow / sim-account pipeline (08 §2-§3, WP9)."""

from yquant.paper.broker import (
    PaperBroker,
    PaperConfig,
    build_paper_result,
    run_paper,
)
from yquant.paper.execution import (
    ExecutionQualityReport,
    RealizedFill,
    backfill_execution_quality,
)
from yquant.paper.parity import (
    ParityReport,
    parity_report,
    shadow_reconciliation,
)

__all__ = [
    "ExecutionQualityReport",
    "PaperBroker",
    "PaperConfig",
    "ParityReport",
    "RealizedFill",
    "backfill_execution_quality",
    "build_paper_result",
    "parity_report",
    "run_paper",
    "shadow_reconciliation",
]
