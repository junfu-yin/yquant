"""WP7 incident five-step playbook tests (07 §6)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from yquant.ledger import Event, LedgerStore, Provenance, new_event_id
from yquant.ledger.incident import IncidentReport, archive_report, collect_incident


def _prov() -> Provenance:
    return Provenance(git_sha="abc123", config_hash="cfg-1", data_manifest_id="mani-1")


def _event(*, dedup_key: str, minute: int, kind: str = "signal") -> Event:
    moment = datetime(2024, 1, 3, 12, minute, tzinfo=UTC)
    return Event(
        event_id=new_event_id(moment, entropy=bytes([minute]) * 10),
        ts=moment,
        kind=kind,  # type: ignore[arg-type]
        payload={"dedup": dedup_key},
        run_id="run-1",
        dedup_key=dedup_key,
        provenance=_prov(),
    )


def _seed(store: LedgerStore) -> None:
    store.append_event(_event(dedup_key="a", minute=0, kind="data_ingested"))
    store.append_event(_event(dedup_key="b", minute=1, kind="order"))
    store.record_run_digest("run-1")


def test_collect_incident_bundles_evidence(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    _seed(store)

    evidence = collect_incident(store, "run-1")
    assert evidence.run_id == "run-1"
    assert evidence.event_count == 2
    assert set(evidence.kinds) == {"data_ingested", "order"}
    assert evidence.git_shas == ("abc123",)
    assert evidence.replay.strict_ok
    # The bundle serializes cleanly for the evidence file.
    assert evidence.as_dict()["replay"]["consistent"] is True


def test_archive_report_requires_new_test(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    _seed(store)

    report = IncidentReport(
        run_id="run-1",
        phenomenon="unbalanced books",
        impact="NAV off by 3bps",
    )
    # No new_test_ids -> archiving must be rejected (每 P0/P1 沉淀 ≥1 条新测试).
    with pytest.raises(ValueError, match="new test"):
        archive_report(store, report)


def test_archive_report_persists_with_new_test(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    _seed(store)

    report = IncidentReport(
        run_id="run-1",
        phenomenon="unbalanced books",
        impact="NAV off by 3bps",
        root_cause="late correction not guarded",
        layer="data",
        new_test_ids=["test_asof_excludes_rows_recorded_after_cutoff"],
    )
    row_id = archive_report(store, report)
    assert row_id == 1

    incidents = store.list_incidents()
    assert len(incidents) == 1
    assert incidents[0].run_id == "run-1"
    assert incidents[0].report["layer"] == "data"


def test_draft_incident_allows_missing_test(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.db")
    store.bootstrap()
    _seed(store)

    report = IncidentReport(run_id="run-1", phenomenon="p", impact="i")
    # A draft (not yet archived) can be recorded without a follow-up test.
    row_id = archive_report(store, report, status="draft")
    assert row_id == 1
    assert store.list_incidents()[0].status == "draft"
