from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from yquant.ledger import LedgerStore
from yquant.risk.types import RiskEvent


def test_ledger_bootstrap_is_idempotent(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "nested" / "yquant.db")
    store.bootstrap()
    store.bootstrap()

    assert (tmp_path / "nested" / "yquant.db").exists()
    assert store.list_risk_events() == []
    assert store.list_job_runs() == []


def test_ledger_records_and_reads_risk_events(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "yquant.db")
    store.bootstrap()

    event = RiskEvent(
        as_of=date(2024, 1, 3),
        rule="overlay_cap",
        detail={"symbol": "TQQQ", "cap": 0.05},
    )
    row_id = store.record_risk_event(event, recorded_at_utc=datetime(2024, 1, 4, tzinfo=UTC))

    records = store.list_risk_events()
    assert row_id == 1
    assert len(records) == 1
    stored = records[0]
    assert stored.rule == "overlay_cap"
    assert stored.date == date(2024, 1, 3)
    assert stored.detail == {"symbol": "TQQQ", "cap": 0.05}
    assert stored.ts_utc == datetime(2024, 1, 4, tzinfo=UTC)


def test_ledger_records_multiple_events_in_order(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "yquant.db")
    store.bootstrap()

    ids = store.record_risk_events(
        [
            RiskEvent(as_of=date(2024, 1, 3), rule="a", detail={}),
            RiskEvent(as_of=date(2024, 1, 3), rule="b", detail={}),
        ]
    )

    assert ids == [1, 2]
    assert [record.rule for record in store.list_risk_events()] == ["a", "b"]


def test_ledger_records_and_reads_job_runs(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "yquant.db")
    store.bootstrap()

    store.record_job_run(
        job="daily_bars_update",
        status="success",
        detail={"symbols": 3, "failed": 0},
        recorded_at_utc=datetime(2024, 1, 4, 12, 0, tzinfo=UTC),
    )
    store.record_job_run(job="daily_bars_freshness", status="failed", detail={"stale": 1})

    runs = store.list_job_runs()
    assert [run.job for run in runs] == ["daily_bars_update", "daily_bars_freshness"]
    assert runs[0].status == "success"
    assert runs[0].detail == {"symbols": 3, "failed": 0}
    assert runs[1].status == "failed"


def test_ledger_naive_timestamp_is_stored_as_utc(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "yquant.db")
    store.bootstrap()

    store.record_job_run(
        job="j",
        status="success",
        recorded_at_utc=datetime(2024, 1, 4, 9, 30),
    )

    assert store.list_job_runs()[0].ts_utc == datetime(2024, 1, 4, 9, 30, tzinfo=UTC)
