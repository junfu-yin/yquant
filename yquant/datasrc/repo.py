"""Local Parquet-backed DataRepo implementation for M1."""

from __future__ import annotations

from datetime import date
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
from yquant.datasrc.manifest import DataManifest, append_manifest, build_manifest, read_manifests
from yquant.datasrc.quality import check_daily_bars


class LocalDataRepo:
    """Single-machine M1 repository backed by canonical Parquet files."""

    def __init__(self, parquet_dir: str | Path) -> None:
        self.parquet_dir = Path(parquet_dir)
        self.daily_bars_path = self.parquet_dir / "daily_bars.parquet"
        self.manifest_path = self.parquet_dir / "manifests" / "daily_bars.jsonl"

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

    def get_universe(
        self,
        on_date: date,
        market: Literal["us", "all"] = "all",
    ) -> list[str]:
        """Return symbols present on the latest available session at or before ``on_date``."""

        if market not in ("us", "all"):
            raise ValueError("market must be 'us' or 'all'")
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


def _single_source_or_mixed(frame: pd.DataFrame) -> str:
    sources = sorted(str(source).lower() for source in frame["source"].dropna().unique())
    return sources[0] if len(sources) == 1 else "mixed"
