"""Local Parquet-backed DataRepo implementation for M1."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from yquant.datasrc.bars import (
    DAILY_BAR_STORAGE_COLUMNS,
    AdjustmentMode,
    canonicalize_daily_bars,
    normalize_symbols,
    repo_view,
)
from yquant.datasrc.macro import (
    canonicalize_macro_series,
    empty_macro_series,
    latest_macro_by_asof,
)
from yquant.datasrc.manifest import DataManifest, append_manifest, build_manifest, read_manifests
from yquant.datasrc.quality import check_daily_bars
from yquant.datasrc.security_master import (
    canonicalize_security_master,
    empty_security_master,
    listed_symbols_on,
)


class LocalDataRepo:
    """Single-machine M1 repository backed by canonical Parquet files."""

    def __init__(self, parquet_dir: str | Path) -> None:
        self.parquet_dir = Path(parquet_dir)
        self.daily_bars_path = self.parquet_dir / "daily_bars.parquet"
        self.manifest_path = self.parquet_dir / "manifests" / "daily_bars.jsonl"
        self.security_master_path = self.parquet_dir / "security_master.parquet"
        self.macro_series_path = self.parquet_dir / "macro_series.parquet"

    def write_daily_bars(self, frame: pd.DataFrame) -> DataManifest:
        """Validate, upsert, and persist canonical daily bars."""

        bars = canonicalize_daily_bars(frame)
        report = check_daily_bars(bars)
        report.raise_for_errors()

        existing = self._read_daily_bars_storage()
        combined = pd.concat([existing, bars], ignore_index=True) if not existing.empty else bars
        combined = canonicalize_daily_bars(combined)
        combined = combined.sort_values(["symbol", "date", "source", "asof"])
        combined = combined.drop_duplicates(["symbol", "date", "source"], keep="last")
        combined = canonicalize_daily_bars(combined)

        self.daily_bars_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(self.daily_bars_path, index=False)

        source = _single_source_or_mixed(bars)
        manifest = build_manifest(
            bars,
            dataset="daily_bars",
            source=source,
            storage_path=self.daily_bars_path,
        )
        append_manifest(self.manifest_path, manifest)
        return manifest

    def get_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adjust: AdjustmentMode = "adjusted",
    ) -> pd.DataFrame:
        """Return daily bars for ``symbols`` in inclusive ``[start, end]``."""

        if end < start:
            raise ValueError("end must be on or after start")
        wanted = set(normalize_symbols(symbols))
        storage = self._read_daily_bars_storage()
        if storage.empty or not wanted:
            return repo_view(storage, adjust)

        dates = pd.to_datetime(storage["date"]).dt.date
        mask = storage["symbol"].astype(str).isin(wanted) & (dates >= start) & (dates <= end)
        return repo_view(storage.loc[mask].copy(), adjust)

    def get_bars_asof(
        self,
        symbols: list[str],
        start: date,
        end: date,
        as_of_utc: datetime,
        adjust: AdjustmentMode = "adjusted",
    ) -> pd.DataFrame:
        """Return bars as they were known at ``as_of_utc`` (point-in-time replay).

        Rows recorded (``asof``) after the cutoff are excluded, so a backtest
        reading at a past instant never sees data — including late corrections —
        that had not yet arrived. This is the lookahead guard for replay.

        Note: storage keeps a single (latest) version per symbol/date/source, so
        a correction overwrites its prior value. This guard therefore prevents
        seeing future-recorded rows but cannot reconstruct an overwritten earlier
        version; full bitemporal history is future work.
        """

        if end < start:
            raise ValueError("end must be on or after start")
        cutoff = _aware_utc_ts(as_of_utc)
        wanted = set(normalize_symbols(symbols))
        storage = self._read_daily_bars_storage()
        if storage.empty or not wanted:
            return repo_view(storage, adjust)

        dates = pd.to_datetime(storage["date"]).dt.date
        asof = pd.to_datetime(storage["asof"], utc=True)
        mask = (
            storage["symbol"].astype(str).isin(wanted)
            & (dates >= start)
            & (dates <= end)
            & (asof <= cutoff)
        )
        return repo_view(storage.loc[mask].copy(), adjust)

    def get_daily_bars_storage(
        self,
        symbols: list[str],
        start: date,
        end: date,
        *,
        sources: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return canonical storage rows, optionally filtered by source."""

        if end < start:
            raise ValueError("end must be on or after start")
        wanted = set(normalize_symbols(symbols))
        storage = self._read_daily_bars_storage()
        if storage.empty or not wanted:
            return storage

        dates = pd.to_datetime(storage["date"]).dt.date
        mask = storage["symbol"].astype(str).isin(wanted) & (dates >= start) & (dates <= end)
        if sources is not None:
            wanted_sources = {source.strip().lower() for source in sources if source.strip()}
            mask &= storage["source"].astype(str).isin(wanted_sources)
        return canonicalize_daily_bars(storage.loc[mask].copy())

    def write_security_master(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Validate and persist the canonical security master (full replace)."""

        master = canonicalize_security_master(frame)
        self.security_master_path.parent.mkdir(parents=True, exist_ok=True)
        master.to_parquet(self.security_master_path, index=False)
        return master

    def get_security_master(self) -> pd.DataFrame:
        """Return the persisted security master, or an empty canonical frame."""

        if not self.security_master_path.exists():
            return empty_security_master()
        return canonicalize_security_master(pd.read_parquet(self.security_master_path))

    def write_macro_series(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Validate, upsert, and persist canonical macro/index series rows."""

        incoming = canonicalize_macro_series(frame)
        existing = self._read_macro_series()
        combined = (
            pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming
        )
        combined = canonicalize_macro_series(combined)
        self.macro_series_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(self.macro_series_path, index=False)
        return incoming

    def get_macro_series(
        self,
        series_ids: list[str],
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """Return the latest-known macro series rows in inclusive ``[start, end]``.

        Bitemporal storage keeps every revision; the current view collapses to
        the freshest ``asof`` per series/date/source.
        """

        if end < start:
            raise ValueError("end must be on or after start")
        wanted = {s.strip().upper() for s in series_ids if s.strip()}
        storage = self._read_macro_series()
        if storage.empty or not wanted:
            return empty_macro_series()
        dates = pd.to_datetime(storage["date"]).dt.date
        mask = storage["series_id"].astype(str).isin(wanted) & (dates >= start) & (dates <= end)
        return latest_macro_by_asof(canonicalize_macro_series(storage.loc[mask].copy()))

    def get_macro_series_asof(
        self,
        series_ids: list[str],
        start: date,
        end: date,
        as_of_utc: datetime,
    ) -> pd.DataFrame:
        """Return macro series as known at ``as_of_utc`` (07 §3 bitemporal replay).

        Official revisions (e.g. an NFCI backfill) arrive as new rows with a
        later ``asof``; a replay reading at a past instant must not see them, so
        an old manifest replays unchanged (T11 over macro series).
        """

        if end < start:
            raise ValueError("end must be on or after start")
        cutoff = _aware_utc_ts(as_of_utc)
        wanted = {s.strip().upper() for s in series_ids if s.strip()}
        storage = self._read_macro_series()
        if storage.empty or not wanted:
            return empty_macro_series()
        dates = pd.to_datetime(storage["date"]).dt.date
        asof = pd.to_datetime(storage["asof"], utc=True)
        mask = (
            storage["series_id"].astype(str).isin(wanted)
            & (dates >= start)
            & (dates <= end)
            & (asof <= cutoff)
        )
        return latest_macro_by_asof(canonicalize_macro_series(storage.loc[mask].copy()))

    def _read_macro_series(self) -> pd.DataFrame:
        if not self.macro_series_path.exists():
            return empty_macro_series()
        return canonicalize_macro_series(pd.read_parquet(self.macro_series_path))

    def get_universe(
        self,
        on_date: date,
        market: Literal["us", "all"] = "all",
    ) -> list[str]:
        """Return the tradable universe on ``on_date``.

        When a security master is present the answer is survivorship-safe: it
        includes names that were listed and not yet delisted on ``on_date``,
        even if they have since delisted. Without a security master it falls back
        to bar presence on the latest session at or before ``on_date``.
        """

        if market not in ("us", "all"):
            raise ValueError("market must be 'us' or 'all'")

        master = self.get_security_master()
        if not master.empty:
            market_filter = None if market == "all" else market
            return listed_symbols_on(master, on_date, market=market_filter)

        storage = self._read_daily_bars_storage()
        if storage.empty:
            return []

        dates = pd.to_datetime(storage["date"]).dt.date
        eligible = storage.loc[dates <= on_date].copy()
        if market != "all":
            eligible = eligible.loc[eligible["market"].astype(str) == market]
        if eligible.empty:
            return []

        eligible_dates = pd.to_datetime(eligible["date"]).dt.date
        last_session = eligible_dates.max()
        session_rows = eligible.loc[eligible_dates == last_session]
        return normalize_symbols(str(symbol) for symbol in session_rows["symbol"].unique())

    def list_manifests(self) -> list[DataManifest]:
        """Return persisted daily-bar manifest records."""

        return read_manifests(self.manifest_path)

    def _read_daily_bars_storage(self) -> pd.DataFrame:
        if not self.daily_bars_path.exists():
            return pd.DataFrame(columns=list(DAILY_BAR_STORAGE_COLUMNS))
        frame = pd.read_parquet(self.daily_bars_path)
        return canonicalize_daily_bars(frame)


def _aware_utc_ts(value: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(UTC)
    return ts.tz_convert(UTC)


def _single_source_or_mixed(frame: pd.DataFrame) -> str:
    sources = sorted(str(source).lower() for source in frame["source"].dropna().unique())
    return sources[0] if len(sources) == 1 else "mixed"
