"""SQLite-backed ledger for risk events and scheduled job runs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from yquant.ledger.schemas import Event, Provenance
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

_REGIME_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS regime_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    date TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    composite REAL NOT NULL,
    detail_json TEXT NOT NULL
)
"""

_DECISION_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    ts_utc TEXT NOT NULL,
    kind TEXT NOT NULL,
    run_id TEXT NOT NULL,
    dedup_key TEXT NOT NULL UNIQUE,
    causation_id TEXT,
    payload_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL
)
"""

_RUN_DIGESTS_DDL = """
CREATE TABLE IF NOT EXISTS run_digests (
    run_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    digest TEXT NOT NULL,
    event_count INTEGER NOT NULL
)
"""

_INCIDENTS_DDL = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    report_json TEXT NOT NULL
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


@dataclass(frozen=True)
class RegimeRecord:
    id: int
    ts_utc: datetime
    date: date
    state: str
    composite: float
    detail: dict[str, Any]


@dataclass(frozen=True)
class EventRecord:
    id: int
    event: Event


@dataclass(frozen=True)
class RunDigestRecord:
    run_id: str
    ts_utc: datetime
    digest: str
    event_count: int


@dataclass(frozen=True)
class IncidentRecord:
    id: int
    ts_utc: datetime
    run_id: str
    status: str
    report: dict[str, Any]


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
            conn.execute(_REGIME_HISTORY_DDL)
            conn.execute(_DECISION_EVENTS_DDL)
            conn.execute(_RUN_DIGESTS_DDL)
            conn.execute(_INCIDENTS_DDL)
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

        if not events:
            return []
        recorded_at = _aware_utc(recorded_at_utc or datetime.now(UTC))
        rows = [event.to_row() for event in events]
        with closing(self._connect()) as conn:
            cursors = [
                conn.execute(
                    "INSERT INTO risk_events (ts_utc, date, rule, detail_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        recorded_at.isoformat(),
                        str(row["date"]),
                        str(row["rule"]),
                        json.dumps(row["detail_json"], ensure_ascii=True, sort_keys=True),
                    ),
                )
                for row in rows
            ]
            conn.commit()
            return [int(cursor.lastrowid or 0) for cursor in cursors]

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

    def record_regime(
        self,
        *,
        as_of: date,
        state: str,
        composite: float,
        detail: dict[str, Any] | None = None,
        recorded_at_utc: datetime | None = None,
    ) -> int:
        """Persist (or replace) one day's regime reading; returns its row id.

        The ``date`` column is unique: re-running a day's evaluation overwrites
        the prior row so a replay stays idempotent (07).
        """

        recorded_at = _aware_utc(recorded_at_utc or datetime.now(UTC))
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO regime_history (ts_utc, date, state, composite, detail_json) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET "
                "ts_utc=excluded.ts_utc, state=excluded.state, "
                "composite=excluded.composite, detail_json=excluded.detail_json",
                (
                    recorded_at.isoformat(),
                    as_of.isoformat(),
                    state,
                    float(composite),
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

    def list_regime_history(self, *, limit: int | None = None) -> list[RegimeRecord]:
        query = (
            "SELECT id, ts_utc, date, state, composite, detail_json "
            "FROM regime_history ORDER BY date"
        )
        rows = self._fetch(query, limit)
        return [
            RegimeRecord(
                id=int(row[0]),
                ts_utc=_parse_utc(str(row[1])),
                date=date.fromisoformat(str(row[2])),
                state=str(row[3]),
                composite=float(row[4]),
                detail=json.loads(row[5]),
            )
            for row in rows
        ]

    # ---- Decision-event ledger (07 §1-2) ---------------------------------

    def append_event(self, event: Event) -> EventRecord:
        """Append one decision event, idempotent on ``dedup_key`` (T8).

        A second write carrying the same ``dedup_key`` returns the already
        persisted record untouched instead of inserting a duplicate, so a
        re-run of the daily pipeline never double-books a fact.
        """

        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO decision_events "
                "(event_id, ts_utc, kind, run_id, dedup_key, causation_id, "
                "payload_json, provenance_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(dedup_key) DO NOTHING",
                (
                    event.event_id,
                    event.ts.astimezone(UTC).isoformat(),
                    event.kind,
                    event.run_id,
                    event.dedup_key,
                    event.causation_id,
                    json.dumps(event.payload, ensure_ascii=True, sort_keys=True, default=str),
                    json.dumps(
                        event.provenance.model_dump(), ensure_ascii=True, sort_keys=True
                    ),
                ),
            )
            conn.commit()
            if cursor.rowcount == 1:
                return EventRecord(id=int(cursor.lastrowid or 0), event=event)
            row = conn.execute(
                "SELECT id, event_id, ts_utc, kind, run_id, dedup_key, causation_id, "
                "payload_json, provenance_json FROM decision_events WHERE dedup_key = ?",
                (event.dedup_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("deduplicated event could not be read back")
            return _row_to_event_record(row)

    def get_event_by_dedup(self, dedup_key: str) -> EventRecord | None:
        rows = self._fetch_where(
            "SELECT id, event_id, ts_utc, kind, run_id, dedup_key, causation_id, "
            "payload_json, provenance_json FROM decision_events WHERE dedup_key = ?",
            (dedup_key,),
        )
        if not rows:
            return None
        return _row_to_event_record(rows[0])

    def list_events(self, *, run_id: str | None = None) -> list[EventRecord]:
        """Return decision events ordered by ``event_id`` (ULID = time order)."""

        base = (
            "SELECT id, event_id, ts_utc, kind, run_id, dedup_key, causation_id, "
            "payload_json, provenance_json FROM decision_events"
        )
        if run_id is not None:
            rows = self._fetch_where(f"{base} WHERE run_id = ? ORDER BY event_id", (run_id,))
        else:
            rows = self._fetch_where(f"{base} ORDER BY event_id", ())
        return [_row_to_event_record(row) for row in rows]

    def causal_chain(self, event_id: str) -> list[EventRecord]:
        """Walk ``causation_id`` links from ``event_id`` back to the root.

        Returns the chain oldest-first (root … leaf) so a UI can render a fill
        back to the raw data partition that ultimately caused it (07 §2).
        """

        by_id = {rec.event.event_id: rec for rec in self.list_events()}
        chain: list[EventRecord] = []
        cursor: str | None = event_id
        seen: set[str] = set()
        while cursor is not None and cursor in by_id and cursor not in seen:
            seen.add(cursor)
            record = by_id[cursor]
            chain.append(record)
            cursor = record.event.causation_id
        chain.reverse()
        return chain

    # ---- Run digest (07 §4) ----------------------------------------------

    def compute_run_digest(self, run_id: str) -> str:
        """Merkle-root the run's events (07 §4): hash leaves, then fold pairs."""

        events = [rec.event for rec in self.list_events(run_id=run_id)]
        return compute_merkle_root(events)

    def record_run_digest(
        self, run_id: str, *, recorded_at_utc: datetime | None = None
    ) -> RunDigestRecord:
        """Compute and persist the run digest, overwriting on re-run (idempotent)."""

        events = self.list_events(run_id=run_id)
        digest = compute_merkle_root([rec.event for rec in events])
        recorded_at = _aware_utc(recorded_at_utc or datetime.now(UTC))
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO run_digests (run_id, ts_utc, digest, event_count) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET "
                "ts_utc=excluded.ts_utc, digest=excluded.digest, "
                "event_count=excluded.event_count",
                (run_id, recorded_at.isoformat(), digest, len(events)),
            )
            conn.commit()
        return RunDigestRecord(
            run_id=run_id, ts_utc=recorded_at, digest=digest, event_count=len(events)
        )

    def get_run_digest(self, run_id: str) -> RunDigestRecord | None:
        rows = self._fetch_where(
            "SELECT run_id, ts_utc, digest, event_count FROM run_digests WHERE run_id = ?",
            (run_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return RunDigestRecord(
            run_id=str(row[0]),
            ts_utc=_parse_utc(str(row[1])),
            digest=str(row[2]),
            event_count=int(row[3]),
        )

    # ---- Incidents (07 §6) -----------------------------------------------

    def record_incident(
        self,
        *,
        run_id: str,
        status: str,
        report: dict[str, Any],
        recorded_at_utc: datetime | None = None,
    ) -> int:
        recorded_at = _aware_utc(recorded_at_utc or datetime.now(UTC))
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO incidents (ts_utc, run_id, status, report_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    recorded_at.isoformat(),
                    run_id,
                    status,
                    json.dumps(report, ensure_ascii=True, sort_keys=True, default=str),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def list_incidents(self, *, limit: int | None = None) -> list[IncidentRecord]:
        query = "SELECT id, ts_utc, run_id, status, report_json FROM incidents ORDER BY id"
        rows = self._fetch(query, limit)
        return [
            IncidentRecord(
                id=int(row[0]),
                ts_utc=_parse_utc(str(row[1])),
                run_id=str(row[2]),
                status=str(row[3]),
                report=json.loads(row[4]),
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
                if limit < 0:
                    raise ValueError("limit must be non-negative")
                cursor = conn.execute(f"{query} LIMIT ?", (int(limit),))
            else:
                cursor = conn.execute(query)
            return list(cursor.fetchall())

    def _fetch_where(self, query: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with closing(self._connect()) as conn:
            return list(conn.execute(query, params).fetchall())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn


def compute_merkle_root(events: list[Event]) -> str:
    """Merkle root of a run's events (07 §4).

    Leaves are ``sha256(canonical_bytes)`` in ``event_id`` order; internal nodes
    are ``sha256(left + right)``. An odd node is promoted unchanged. An empty run
    hashes to ``sha256(b"")`` so a no-op day still has a stable digest.
    """

    if not events:
        return hashlib.sha256(b"").hexdigest()
    ordered = sorted(events, key=lambda e: e.event_id)
    layer = [hashlib.sha256(event.canonical_bytes()).digest() for event in ordered]
    while len(layer) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(layer), 2):
            left = layer[i]
            right = layer[i + 1] if i + 1 < len(layer) else layer[i]
            nxt.append(hashlib.sha256(left + right).digest())
        layer = nxt
    return layer[0].hex()


def _row_to_event_record(row: tuple[Any, ...]) -> EventRecord:
    provenance = Provenance(**json.loads(row[8]))
    event = Event(
        event_id=str(row[1]),
        ts=_parse_utc(str(row[2])),
        kind=str(row[3]),  # type: ignore[arg-type]
        run_id=str(row[4]),
        dedup_key=str(row[5]),
        causation_id=None if row[6] is None else str(row[6]),
        payload=json.loads(row[7]),
        provenance=provenance,
    )
    return EventRecord(id=int(row[0]), event=event)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return _aware_utc(value)
