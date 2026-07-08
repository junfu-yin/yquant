"""SQLite-backed ledger for risk events and scheduled job runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from yquant.risk.types import RiskEvent

_RISK_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    date TEXT NOT NULL,
    rule TEXT NOT NULL,
    detail_json TEXT NOT NULL
)
"""

_JOB_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    job TEXT NOT NULL,
    status TEXT NOT NULL,
    detail_json TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class RiskEventRecord:
    id: int
    ts_utc: datetime
    date: date
    rule: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class JobRunRecord:
    id: int
    ts_utc: datetime
    job: str
    status: str
    detail: dict[str, Any]


class LedgerStore:
    """Single-file SQLite ledger. Cheap to open; safe to bootstrap repeatedly."""

    def __init__(self, sqlite_path: str | Path) -> None:
        self.sqlite_path = Path(sqlite_path)

    def bootstrap(self) -> None:
        """Create the ledger tables if they do not already exist."""

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute(_RISK_EVENTS_DDL)
            conn.execute(_JOB_RUNS_DDL)
            conn.commit()

    def record_risk_event(
        self,
        event: RiskEvent,
        *,
        recorded_at_utc: datetime | None = None,
    ) -> int:
        """Persist a :class:`RiskEvent` and return its assigned row id."""

        row = event.to_row()
        return self._insert_risk_event(
            date_iso=str(row["date"]),
            rule=str(row["rule"]),
            detail=row["detail_json"],
            recorded_at_utc=recorded_at_utc,
        )

    def record_risk_events(
        self,
        events: list[RiskEvent],
        *,
        recorded_at_utc: datetime | None = None,
    ) -> list[int]:
        """Persist multiple risk events, returning their row ids in order."""

        return [
            self.record_risk_event(event, recorded_at_utc=recorded_at_utc) for event in events
        ]

    def record_job_run(
        self,
        *,
        job: str,
        status: str,
        detail: dict[str, Any] | None = None,
        recorded_at_utc: datetime | None = None,
    ) -> int:
        """Persist one scheduled-job outcome and return its assigned row id."""

        recorded_at = _aware_utc(recorded_at_utc or datetime.now(UTC))
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO job_runs (ts_utc, job, status, detail_json) VALUES (?, ?, ?, ?)",
                (
                    recorded_at.isoformat(),
                    job,
                    status,
                    json.dumps(detail or {}, ensure_ascii=True, sort_keys=True),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def list_risk_events(self, *, limit: int | None = None) -> list[RiskEventRecord]:
        query = "SELECT id, ts_utc, date, rule, detail_json FROM risk_events ORDER BY id"
        rows = self._fetch(query, limit)
        return [
            RiskEventRecord(
                id=int(row[0]),
                ts_utc=_parse_utc(str(row[1])),
                date=date.fromisoformat(str(row[2])),
                rule=str(row[3]),
                detail=json.loads(row[4]),
            )
            for row in rows
        ]

    def list_job_runs(self, *, limit: int | None = None) -> list[JobRunRecord]:
        query = "SELECT id, ts_utc, job, status, detail_json FROM job_runs ORDER BY id"
        rows = self._fetch(query, limit)
        return [
            JobRunRecord(
                id=int(row[0]),
                ts_utc=_parse_utc(str(row[1])),
                job=str(row[2]),
                status=str(row[3]),
                detail=json.loads(row[4]),
            )
            for row in rows
        ]

    def _insert_risk_event(
        self,
        *,
        date_iso: str,
        rule: str,
        detail: Any,
        recorded_at_utc: datetime | None,
    ) -> int:
        recorded_at = _aware_utc(recorded_at_utc or datetime.now(UTC))
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO risk_events (ts_utc, date, rule, detail_json) VALUES (?, ?, ?, ?)",
                (
                    recorded_at.isoformat(),
                    date_iso,
                    rule,
                    json.dumps(detail, ensure_ascii=True, sort_keys=True),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def _fetch(self, query: str, limit: int | None) -> list[tuple[Any, ...]]:
        with closing(self._connect()) as conn:
            if limit is not None:
                cursor = conn.execute(f"{query} LIMIT ?", (int(limit),))
            else:
                cursor = conn.execute(query)
            return list(cursor.fetchall())

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.sqlite_path)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return _aware_utc(value)
