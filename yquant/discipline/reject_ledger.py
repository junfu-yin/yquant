"""Persist proposal-guardrail rejections as risk_events.

v3.1a requires every refused suggestion to leave evidence: a rejected 2x request
or an overlay-cap breach must be auditable after the fact. This bridges the M5
proposal path to the SQLite ledger without either side importing the other's
internals.
"""

from __future__ import annotations

from datetime import date

from yquant.discipline.overlay_guardrails import OverlayViolation
from yquant.discipline.proposals import ProposalValidationError
from yquant.ledger import LedgerStore
from yquant.risk.types import RiskEvent

REJECT_RULE_PREFIX = "proposal_reject"


def overlay_violations_to_events(
    violations: list[OverlayViolation],
    *,
    as_of: date,
) -> list[RiskEvent]:
    """Map guardrail violations to replayable risk_events."""

    return [
        RiskEvent(
            as_of=as_of,
            rule=f"{REJECT_RULE_PREFIX}:{violation.rule}",
            detail=dict(violation.detail),
        )
        for violation in violations
    ]


def record_proposal_rejection(
    store: LedgerStore,
    error: ProposalValidationError,
    *,
    as_of: date,
) -> list[int]:
    """Ledger a proposal rejection and return the created risk_event ids.

    Guardrail breaches produce one event per violation; a metadata/validation
    failure with no structured violations produces a single generic event so no
    rejection goes unrecorded.
    """

    if error.violations:
        events = overlay_violations_to_events(error.violations, as_of=as_of)
    else:
        events = [
            RiskEvent(
                as_of=as_of,
                rule=REJECT_RULE_PREFIX,
                detail={"symbol": error.symbol, "message": str(error)},
            )
        ]
    return store.record_risk_events(events)
