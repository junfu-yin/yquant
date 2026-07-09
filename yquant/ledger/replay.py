"""Ledger-level replay verification (07 §4).

The v3.1 daily pipeline (strategy → brief → committee) is not yet built, so a
full forward re-drive is future work. What is auditable *today* is the ledger's
own integrity: recompute the run's Merkle root from persisted events and compare
it to the digest recorded at run close. A mismatch means the ledger was mutated
after the fact (append-only violated) or a non-deterministic defect corrupted a
leaf — both are P0-worthy findings. Provenance divergence (git_sha / config_hash
/ data_manifest_id drifting mid-run) is reported alongside so a replay under a
different code or data world is flagged rather than silently "passing".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from yquant.ledger.store import EventRecord, LedgerStore, compute_merkle_root


@dataclass(frozen=True)
class ReplayResult:
    run_id: str
    consistent: bool
    recorded_digest: str | None
    recomputed_digest: str
    event_count: int
    first_divergence: str | None = None
    provenance_warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def strict_ok(self) -> bool:
        """Strict replay passes only with a consistent digest and no warnings."""

        return self.consistent and not self.provenance_warnings


def replay_run(store: LedgerStore, run_id: str) -> ReplayResult:
    """Recompute and verify a run's digest against the ledger (07 §4).

    Callers decide strictness via :attr:`ReplayResult.strict_ok`, which folds
    provenance drift into the verdict so a replay under a different git_sha /
    config / manifest cannot quietly succeed.
    """

    records = store.list_events(run_id=run_id)
    events = [rec.event for rec in records]
    recomputed = compute_merkle_root(events)

    recorded_row = store.get_run_digest(run_id)
    recorded = recorded_row.digest if recorded_row is not None else None
    consistent = recorded is not None and recorded == recomputed

    warnings: list[str] = []
    git_shas = {e.provenance.git_sha for e in events}
    config_hashes = {e.provenance.config_hash for e in events}
    manifests = {e.provenance.data_manifest_id for e in events}
    if len(git_shas) > 1:
        warnings.append(f"git_sha drift within run: {sorted(git_shas)}")
    if len(config_hashes) > 1:
        warnings.append(f"config_hash drift within run: {sorted(config_hashes)}")
    if len(manifests) > 1:
        warnings.append(f"data_manifest_id drift within run: {sorted(manifests)}")

    first_divergence = None
    if recorded is not None and not consistent:
        first_divergence = _first_divergent_event(records)

    return ReplayResult(
        run_id=run_id,
        consistent=consistent,
        recorded_digest=recorded,
        recomputed_digest=recomputed,
        event_count=len(events),
        first_divergence=first_divergence,
        provenance_warnings=tuple(warnings),
    )


def _first_divergent_event(records: list[EventRecord]) -> str | None:
    """Best-effort locator of the earliest event that breaks digest continuity.

    With only the persisted ledger we cannot diff against a golden re-drive, so
    we surface the first event whose id ordering is not strictly increasing —
    the most common corruption signature (reordering / duplicate insertion).
    """

    previous_id = ""
    for rec in records:
        if rec.event.event_id <= previous_id:
            return f"{rec.event.kind}:{rec.event.event_id}"
        previous_id = rec.event.event_id
    return records[0].event.event_id if records else None
