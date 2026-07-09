"""M9 macro radar Layer-2/3: hawk/dove scoring, macro cards, and the committee.

Layer-1 (the regime state machine) lives in :mod:`yquant.risk`; this package adds
the LLM-facing layers the plan governs deterministically (03 §5.9, ADR-32/34):

* :mod:`yquant.macro.hawk_dove` — a five-tier central-bank scorer + a frozen
  calibration set with the quarterly recalibration gate (06 §6);
* :mod:`yquant.macro.schemas` — MacroEventCard and the committee artefacts, with
  the machine-readable-invalidation red line enforced at construction;
* :mod:`yquant.macro.committee` — the analyst -> red team -> synthesis pipeline
  with the Overlay budgeter and state-machine veto (T18).
"""

from yquant.macro.committee import (
    OVERLAY_SINGLE_CAP,
    OVERLAY_TOTAL_CAP,
    CommitteeConfig,
    budget_theses,
    red_team_reject,
    run_committee,
)
from yquant.macro.hawk_dove import (
    CALIBRATION_MAX_MAD,
    HAWK_DOVE_MAX,
    HAWK_DOVE_MIN,
    CalibrationReport,
    CalibrationSample,
    build_calibration_set,
    calibrate,
    run_calibration,
    score_hawk_dove,
)
from yquant.macro.schemas import (
    CommitteeOutput,
    CoreTiltSuggestion,
    MacroEventCard,
    OpportunityBookEntry,
    RejectedThesis,
    RiskDashboardItem,
    ThesisProposal,
    is_machine_readable_condition,
)

__all__ = [
    "CALIBRATION_MAX_MAD",
    "HAWK_DOVE_MAX",
    "HAWK_DOVE_MIN",
    "OVERLAY_SINGLE_CAP",
    "OVERLAY_TOTAL_CAP",
    "CalibrationReport",
    "CalibrationSample",
    "CommitteeConfig",
    "CommitteeOutput",
    "CoreTiltSuggestion",
    "MacroEventCard",
    "OpportunityBookEntry",
    "RejectedThesis",
    "RiskDashboardItem",
    "ThesisProposal",
    "budget_theses",
    "build_calibration_set",
    "calibrate",
    "is_machine_readable_condition",
    "red_team_reject",
    "run_calibration",
    "run_committee",
    "score_hawk_dove",
]
