"""WP7 ledger-level replay verification tests (07 §4, T13)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from yquant.ledger import Event, LedgerStore, Provenance, new_event_id
from yquant.ledger.replay import replay_run


def _prov(**overrides: object) -> Provenance:
    base: dict[str, object] = {
        "git_sha": "abc123",
        "config_hash": "cfg-1",
        "data_manifest_id": "mani-1",
    }
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


def _event(
    *,
    dedup_key: str,
    minute: int,
    provenance: Provenance | None = None,
    entropy: bytes = b"\x00" * 10,
) -> Event:
    moment = datetime(2024, 1, 3, 12, minute, tzinfo=UTC)
    return Event(
        event_id=new_event_id(moment, entropy=entropy),
        ts=moment,
        kind="signal",
        payload={"dedup": dedup_key},
        run_id="run-1",
        dedup_key=dedup_key,
        provenance=provenance or _prov(),
    )


def _seed_run(store: LedgerStore, *, provenance: Provenance | None = None) -> None:
    store.append_event(_event(dedup_key="a", minute=0, entropy=b"\x00" * 10))
    store.append_event(
        _event(dedup_key="b", minute=1, entropy=b"\x01" * 10, provenance=provenance)
    )
    store.record_run_digest("run-1")


def test_replay_consistent_after_faithful_record(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    _seed_run(store)

    result = replay_run(store, "run-1")
    assert result.consistent
    assert result.strict_ok
    assert result.event_count == 2
    assert result.recorded_digest == result.recomputed_digest


def test_replay_detects_post_hoc_mutation(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    store = LedgerStore(db)
    store.bootstrap()
    _seed_run(store)

    # Tamper: rewrite a persisted payload after the digest was recorded.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE decision_events SET payload_json = ? WHERE dedup_key = ?",
            ('{"dedup": "TAMPERED"}', "a"),
        )
        conn.commit()

    result = replay_run(store, "run-1")
    assert not result.consistent
    assert not result.strict_ok
    assert result.recorded_digest != result.recomputed_digest


def test_replay_flags_provenance_drift(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    # Second event carries a different git_sha -> replay under a mixed code world.
    _seed_run(store, provenance=_prov(git_sha="def456"))

    result = replay_run(store, "run-1")
    # Digest still matches what was recorded, but strict replay must fail on drift.
    assert result.consistent
    assert not result.strict_ok
    assert any("git_sha drift" in w for w in result.provenance_warnings)


def test_replay_missing_digest_is_inconsistent(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    store.append_event(_event(dedup_key="a", minute=0))
    # No record_run_digest call -> nothing to compare against.

    result = replay_run(store, "run-1")
    assert result.recorded_digest is None
    assert not result.consistent
