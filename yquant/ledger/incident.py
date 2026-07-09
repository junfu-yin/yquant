"""Incident forensics five-step playbook (07 §6).

Freeze → collect → replay → bisect → archive. Anything "off" (bad proposal,
missed red flag, unbalanced books, weird NAV) goes through here; nobody edits
data to "fix" it. ``collect`` bundles the evidence a post-mortem needs — event
chain, run digest, provenance snapshot — and ``archive_report`` persists the
templated report. Every P0/P1 must land ≥1 new test whose id is filled back in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yquant.ledger.replay import ReplayResult, replay_run
from yquant.ledger.store import LedgerStore


@dataclass(frozen=True)
class IncidentEvidence:
    """The one-command evidence bundle (07 §6 step 2)."""

    run_id: str
    collected_at: datetime
    event_count: int
    event_ids: tuple[str, ...]
    kinds: tuple[str, ...]
    git_shas: tuple[str, ...]
    config_hashes: tuple[str, ...]
    data_manifest_ids: tuple[str, ...]
    replay: ReplayResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "collected_at": self.collected_at.isoformat(),
            "event_count": self.event_count,
            "event_ids": list(self.event_ids),
            "kinds": list(self.kinds),
            "git_shas": list(self.git_shas),
            "config_hashes": list(self.config_hashes),
            "data_manifest_ids": list(self.data_manifest_ids),
            "replay": {
                "consistent": self.replay.consistent,
                "strict_ok": self.replay.strict_ok,
                "recorded_digest": self.replay.recorded_digest,
                "recomputed_digest": self.replay.recomputed_digest,
                "first_divergence": self.replay.first_divergence,
                "provenance_warnings": list(self.replay.provenance_warnings),
            },
        }


@dataclass
class IncidentReport:
    """Archived post-mortem template (07 §6 step 5)."""

    run_id: str
    phenomenon: str
    impact: str
    root_cause: str = ""
    timeline: list[str] = field(default_factory=list)
    involved_event_ids: list[str] = field(default_factory=list)
    fix: str = ""
    prevention: str = ""
    new_test_ids: list[str] = field(default_factory=list)
    layer: str = "unknown"  # data / code / config / model (step 4 bisection)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "phenomenon": self.phenomenon,
            "impact": self.impact,
            "root_cause": self.root_cause,
            "timeline": list(self.timeline),
            "involved_event_ids": list(self.involved_event_ids),
            "fix": self.fix,
            "prevention": self.prevention,
            "new_test_ids": list(self.new_test_ids),
            "layer": self.layer,
        }


def collect_incident(
    store: LedgerStore, run_id: str, *, collected_at: datetime | None = None
) -> IncidentEvidence:
    """Step 2: one-shot evidence bundle for ``run_id`` (07 §6)."""

    records = store.list_events(run_id=run_id)
    events = [rec.event for rec in records]
    replay = replay_run(store, run_id)
    moment = (collected_at or datetime.now(UTC)).astimezone(UTC)
    return IncidentEvidence(
        run_id=run_id,
        collected_at=moment,
        event_count=len(events),
        event_ids=tuple(e.event_id for e in events),
        kinds=tuple(dict.fromkeys(e.kind for e in events)),
        git_shas=tuple(sorted({e.provenance.git_sha for e in events})),
        config_hashes=tuple(sorted({e.provenance.config_hash for e in events})),
        data_manifest_ids=tuple(sorted({e.provenance.data_manifest_id for e in events})),
        replay=replay,
    )


def archive_report(
    store: LedgerStore,
    report: IncidentReport,
    *,
    status: str = "archived",
    recorded_at_utc: datetime | None = None,
) -> int:
    """Step 5: persist a post-mortem, rejecting one with no follow-up test.

    Enforcing ``new_test_ids`` at archive time makes "每 P0/P1 沉淀 ≥1 条新测试"
    a hard gate rather than a good intention.
    """

    if status == "archived" and not report.new_test_ids:
        raise ValueError("an archived incident must cite at least one new test id (07 §6)")
    return store.record_incident(
        run_id=report.run_id,
        status=status,
        report=report.as_dict(),
        recorded_at_utc=recorded_at_utc,
    )
