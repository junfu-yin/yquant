"""Macro / index level series storage and update.

Daily bars cover tradable securities; macro drivers (index levels, ^VIX) live in
their own long-format series table so the risk regime and dynamic gates have a
single, quality-checked source. Values are stored as-reported levels.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol, cast

import pandas as pd

MACRO_SERIES_COLUMNS: tuple[str, ...] = ("series_id", "date", "value", "source", "asof")

MacroAttemptStatus = Literal["success", "empty", "failed"]


class MacroSeriesSource(Protocol):
    """Minimal protocol for a source of macro/index level series."""

    name: str

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.DataFrame:
        """Fetch a long-format ``date,value`` frame for one series."""


@dataclass(frozen=True)
class MacroSeriesAttempt:
    series_id: str
    source: str
    status: MacroAttemptStatus
    row_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class MacroUpdateReport:
    dataset: str
    series_ids: tuple[str, ...]
    start: date
    end: date
    attempts: tuple[MacroSeriesAttempt, ...]
    failed_series: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failed_series and bool(self.series_ids)


def canonicalize_macro_series(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a typed macro-series frame, keeping one row per version.

    Storage is bitemporal (07 §3): an official revision arrives as a new row
    carrying a later ``asof`` rather than overwriting the original. Deduplication
    therefore keys on ``(series_id, date, source, asof)`` so every version is
    preserved; collapsing to the value known at a point in time is a *read*
    concern handled by :func:`latest_macro_by_asof`.
    """

    missing = [column for column in ("series_id", "date", "value") if column not in frame]
    if missing:
        raise ValueError(f"macro series missing required columns: {missing}")

    out = frame.copy()
    if "source" not in out.columns:
        out["source"] = "unknown"
    if "asof" not in out.columns:
        out["asof"] = datetime.now(UTC)

    out = out.loc[:, list(MACRO_SERIES_COLUMNS)].copy()
    out["series_id"] = out["series_id"].astype("string").str.strip().str.upper()
    out["source"] = out["source"].astype("string").str.strip().str.lower()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["asof"] = pd.to_datetime(out["asof"], utc=True)

    out = out.dropna(subset=["value"])
    out = out.sort_values(["series_id", "date", "source", "asof"])
    out = out.drop_duplicates(["series_id", "date", "source", "asof"], keep="last")
    return cast(pd.DataFrame, out.reset_index(drop=True))


def latest_macro_by_asof(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse bitemporal versions to the latest ``asof`` per series/date/source.

    Callers first restrict ``asof`` to their point-in-time cutoff (or take the
    whole frame for the current view); this then picks the freshest version that
    survived that cut, so a revision only wins once its ``asof`` is in scope.
    """

    if frame.empty:
        return frame
    out = frame.sort_values(["series_id", "date", "source", "asof"])
    out = out.drop_duplicates(["series_id", "date", "source"], keep="last")
    return cast(pd.DataFrame, out.reset_index(drop=True))


def empty_macro_series() -> pd.DataFrame:
    frame = pd.DataFrame(columns=list(MACRO_SERIES_COLUMNS))
    frame["asof"] = pd.to_datetime(frame["asof"], utc=True)
    return frame


class YFinanceMacroSource:
    """Macro/index level source using yfinance close levels."""

    name = "yfinance"

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.DataFrame:
        yfinance = importlib.import_module("yfinance")
        download = _required_callable(yfinance, "download")
        raw = download(
            series_id,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            progress=False,
        )
        return normalize_yfinance_macro_series(raw, series_id, source=self.name)


def normalize_yfinance_macro_series(
    frame: pd.DataFrame,
    series_id: str,
    *,
    source: str = "yfinance",
) -> pd.DataFrame:
    """Normalize a yfinance download into ``series_id,date,value`` rows."""

    if frame.empty:
        return empty_macro_series()

    working = frame.copy()
    working.columns = [_flatten_column(column) for column in working.columns]
    if "Date" not in working.columns:
        working = working.reset_index()
        working.columns = [_flatten_column(column) for column in working.columns]

    close = _close_column(working)
    result = pd.DataFrame(
        {
            "series_id": series_id,
            "date": pd.to_datetime(working["Date"]).dt.date,
            "value": pd.to_numeric(close, errors="coerce"),
            "source": source,
            "asof": datetime.now(UTC),
        }
    )
    return canonicalize_macro_series(result)


class MacroUpdater:
    """Fetch macro series from a single source and upsert them into a repo."""

    def __init__(self, repo: Any, source: MacroSeriesSource) -> None:
        self.repo = repo
        self.source = source

    def update(self, series_ids: list[str], start: date, end: date) -> MacroUpdateReport:
        if end < start:
            raise ValueError("end must be on or after start")

        normalized = tuple(dict.fromkeys(s.strip().upper() for s in series_ids if s.strip()))
        attempts: list[MacroSeriesAttempt] = []
        failed: list[str] = []
        accepted: list[pd.DataFrame] = []

        for series_id in normalized:
            try:
                frame = self.source.fetch_series(series_id, start, end)
            except Exception as exc:  # noqa: BLE001 - recorded per series
                attempts.append(
                    MacroSeriesAttempt(
                        series_id=series_id,
                        source=self.source.name,
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                failed.append(series_id)
                continue
            if frame.empty:
                attempts.append(
                    MacroSeriesAttempt(series_id=series_id, source=self.source.name, status="empty")
                )
                failed.append(series_id)
                continue
            canonical = canonicalize_macro_series(frame)
            accepted.append(canonical)
            attempts.append(
                MacroSeriesAttempt(
                    series_id=series_id,
                    source=self.source.name,
                    status="success",
                    row_count=int(len(canonical)),
                )
            )

        if accepted:
            self.repo.write_macro_series(pd.concat(accepted, ignore_index=True))

        return MacroUpdateReport(
            dataset="macro_series",
            series_ids=normalized,
            start=start,
            end=end,
            attempts=tuple(attempts),
            failed_series=tuple(failed),
        )


def _close_column(frame: pd.DataFrame) -> pd.Series:
    for candidate in ("Adj Close", "Close"):
        for column in frame.columns:
            name = str(column)
            if name == candidate or name.startswith(f"{candidate}_"):
                return cast(pd.Series, frame[name])
    raise ValueError("macro source frame missing a Close column")


def _flatten_column(column: Any) -> str:
    if isinstance(column, tuple):
        return "_".join(str(part) for part in column if str(part))
    return str(column)


def _required_callable(module: Any, name: str) -> Callable[..., Any]:
    value = getattr(module, name)
    if not callable(value):
        raise TypeError(f"{module.__name__}.{name} is not callable")
    return cast(Callable[..., Any], value)
