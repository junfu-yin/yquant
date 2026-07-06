"""Freshness checks for persisted M1 daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

import pandas as pd

from yquant.datasrc.bars import normalize_symbols
from yquant.datasrc.protocols import DataRepo

FreshnessStatus = Literal["fresh", "late", "stale", "missing"]


@dataclass(frozen=True)
class DailyBarFreshnessItem:
    symbol: str
    expected_date: date
    latest_date: date | None
    latest_asof_utc: datetime | None
    status: FreshnessStatus
    detail: str


@dataclass(frozen=True)
class DailyBarFreshnessReport:
    dataset: str
    expected_date: date
    deadline_utc: datetime | None
    generated_at_utc: datetime
    items: tuple[DailyBarFreshnessItem, ...]

    @property
    def passed(self) -> bool:
        return all(item.status == "fresh" for item in self.items)


def check_daily_bar_freshness(
    repo: DataRepo,
    symbols: list[str],
    *,
    expected_date: date,
    deadline_utc: datetime | None = None,
    lookback_days: int = 10,
    generated_at_utc: datetime | None = None,
) -> DailyBarFreshnessReport:
    """Check whether each symbol has the expected daily bar by the deadline."""

    if lookback_days < 0:
        raise ValueError("lookback_days must be non-negative")

    normalized_symbols = normalize_symbols(symbols)
    start = expected_date - timedelta(days=lookback_days)
    bars = repo.get_bars(normalized_symbols, start, expected_date, adjust="adjusted")
    deadline = _aware_utc(deadline_utc) if deadline_utc is not None else None
    generated_at = _aware_utc(generated_at_utc or datetime.now(UTC))
    items = tuple(
        _freshness_item(
            bars,
            symbol=symbol,
            expected_date=expected_date,
            deadline_utc=deadline,
        )
        for symbol in normalized_symbols
    )
    return DailyBarFreshnessReport(
        dataset="daily_bars",
        expected_date=expected_date,
        deadline_utc=deadline,
        generated_at_utc=generated_at,
        items=items,
    )


def _freshness_item(
    bars: pd.DataFrame,
    *,
    symbol: str,
    expected_date: date,
    deadline_utc: datetime | None,
) -> DailyBarFreshnessItem:
    symbol_rows = bars.loc[bars["symbol"].astype(str) == symbol].copy()
    if symbol_rows.empty:
        return DailyBarFreshnessItem(
            symbol=symbol,
            expected_date=expected_date,
            latest_date=None,
            latest_asof_utc=None,
            status="missing",
            detail="no bars found in the freshness lookback window",
        )

    symbol_rows["date"] = pd.to_datetime(symbol_rows["date"]).dt.date
    latest_date = symbol_rows["date"].max()
    latest_rows = symbol_rows.loc[symbol_rows["date"] == latest_date]
    latest_asof = _latest_asof_utc(latest_rows)

    if latest_date < expected_date:
        return DailyBarFreshnessItem(
            symbol=symbol,
            expected_date=expected_date,
            latest_date=latest_date,
            latest_asof_utc=latest_asof,
            status="stale",
            detail=f"latest bar date {latest_date.isoformat()} is before expected date",
        )

    if deadline_utc is not None and latest_asof is not None and latest_asof > deadline_utc:
        return DailyBarFreshnessItem(
            symbol=symbol,
            expected_date=expected_date,
            latest_date=latest_date,
            latest_asof_utc=latest_asof,
            status="late",
            detail=f"latest as-of {latest_asof.isoformat()} is after freshness deadline",
        )

    return DailyBarFreshnessItem(
        symbol=symbol,
        expected_date=expected_date,
        latest_date=latest_date,
        latest_asof_utc=latest_asof,
        status="fresh",
        detail="expected daily bar is present by the freshness deadline",
    )


def _latest_asof_utc(rows: pd.DataFrame) -> datetime | None:
    if rows.empty or "asof" not in rows.columns:
        return None
    values = pd.to_datetime(rows["asof"], utc=True, errors="coerce").dropna()
    if values.empty:
        return None
    latest = pd.Timestamp(values.max())
    latest_dt = cast(datetime, latest.to_pydatetime())
    return latest_dt.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
