"""Durable SQLite ledger for risk events, job runs, and decision events.

Both the M1 scheduler (job-run outcomes) and the M5 proposal path (guardrail
rejections) leave replayable evidence here. The 07 decision-event ledger,
provenance envelope, run-digest, and incident records also live in this package
so callers never touch raw SQL.
"""

from yquant.ledger.schemas import (
    Event,
    EventKind,
    Provenance,
    make_dedup_key,
    new_event_id,
)
from yquant.ledger.store import (
    EventRecord,
    IncidentRecord,
    JobRunRecord,
    LedgerStore,
    RegimeRecord,
    RiskEventRecord,
    RunDigestRecord,
    compute_merkle_root,
)

__all__ = [
    "Event",
    "EventKind",
    "EventRecord",
    "IncidentRecord",
    "JobRunRecord",
    "LedgerStore",
    "Provenance",
    "RegimeRecord",
    "RiskEventRecord",
    "RunDigestRecord",
    "compute_merkle_root",
    "make_dedup_key",
    "new_event_id",
]
