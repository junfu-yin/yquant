"""Canonical daily-bar schema for M1 market data storage."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Literal, cast

import pandas as pd

AdjustmentMode = Literal["none", "adjusted"]

DAILY_BAR_STORAGE_COLUMNS: tuple[str, ...] = (
    "symbol",
    "market",
    "date",
    "open_raw",
    "high_raw",
    "low_raw",
    "close_raw",
    "open_adjusted",
    "high_adjusted",
    "low_adjusted",
    "close_adjusted",
    "volume",
    "amount",
    "adj_factor",
    "is_halted",
    "halt_reason",
    "session",
    "source",
    "asof",
)

DAILY_BAR_REPO_COLUMNS: tuple[str, ...] = (
    "symbol",
    "market",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adj_factor",
    "is_halted",
    "halt_reason",
    "session",
    "source",
    "asof",
)

RAW_PRICE_COLUMNS: tuple[str, ...] = ("open_raw", "high_raw", "low_raw", "close_raw")
ADJUSTED_PRICE_COLUMNS: tuple[str, ...] = (
    "open_adjusted",
    "high_adjusted",
    "low_adjusted",
    "close_adjusted",
)
NUMERIC_COLUMNS: tuple[str, ...] = (
    *RAW_PRICE_COLUMNS,
    *ADJUSTED_PRICE_COLUMNS,
    "volume",
    "amount",
    "adj_factor",
)


def utc_now() -> datetime:
    """Return an aware UTC timestamp for as-of bookkeeping."""

    return datetime.now(UTC)


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    """Normalize ticker symbols to the storage convention."""

    return sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})


def canonicalize_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a typed, sorted daily-bar frame in the canonical storage schema."""

    missing = [column for column in DAILY_BAR_STORAGE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"daily bars missing required columns: {missing}")

    out = frame.loc[:, list(DAILY_BAR_STORAGE_COLUMNS)].copy()
    out["symbol"] = out["symbol"].astype("string").str.strip().str.upper()
    out["market"] = out["market"].astype("string").str.strip().str.lower()
    out["source"] = out["source"].astype("string").str.strip().str.lower()
    out["session"] = out["session"].fillna("regular").astype("string").str.strip().str.lower()
    out["halt_reason"] = out["halt_reason"].fillna("").astype("string")
    out["is_halted"] = out["is_halted"].fillna(False).astype(bool)

    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["asof"] = pd.to_datetime(out["asof"], utc=True)
    for column in NUMERIC_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out = out.sort_values(["symbol", "date", "source"]).reset_index(drop=True)
    return cast(pd.DataFrame, out)


def repo_view(frame: pd.DataFrame, adjust: AdjustmentMode = "adjusted") -> pd.DataFrame:
    """Return the DataRepo read shape with adjusted or raw price columns."""

    if adjust not in ("none", "adjusted"):
        raise ValueError("adjust must be 'none' or 'adjusted'")

    source = canonicalize_daily_bars(frame)
    suffix = "raw" if adjust == "none" else "adjusted"
    out = pd.DataFrame(
        {
            "symbol": source["symbol"],
            "market": source["market"],
            "date": source["date"],
            "open": source[f"open_{suffix}"],
            "high": source[f"high_{suffix}"],
            "low": source[f"low_{suffix}"],
            "close": source[f"close_{suffix}"],
            "volume": source["volume"],
            "amount": source["amount"],
            "adj_factor": source["adj_factor"],
            "is_halted": source["is_halted"],
            "halt_reason": source["halt_reason"],
            "session": source["session"],
            "source": source["source"],
            "asof": source["asof"],
        }
    )
    return cast(pd.DataFrame, out.loc[:, list(DAILY_BAR_REPO_COLUMNS)])


def make_daily_bars_frame(
    *,
    symbol: str,
    market: str,
    dates: pd.Series,
    raw_open: pd.Series,
    raw_high: pd.Series,
    raw_low: pd.Series,
    raw_close: pd.Series,
    volume: pd.Series,
    source: str,
    adj_factor: pd.Series | None = None,
    asof: datetime | None = None,
) -> pd.DataFrame:
    """Build canonical daily bars from source-specific raw series."""

    factor = adj_factor if adj_factor is not None else pd.Series(1.0, index=raw_close.index)
    timestamp = asof or utc_now()
    amount = raw_close * volume
    frame = pd.DataFrame(
        {
            "symbol": symbol,
            "market": market,
            "date": dates,
            "open_raw": raw_open,
            "high_raw": raw_high,
            "low_raw": raw_low,
            "close_raw": raw_close,
            "open_adjusted": raw_open * factor,
            "high_adjusted": raw_high * factor,
            "low_adjusted": raw_low * factor,
            "close_adjusted": raw_close * factor,
            "volume": volume,
            "amount": amount,
            "adj_factor": factor,
            "is_halted": False,
            "halt_reason": "",
            "session": "regular",
            "source": source,
            "asof": timestamp,
        }
    )
    return canonicalize_daily_bars(frame)


def date_bounds(frame: pd.DataFrame) -> tuple[date, date]:
    """Return inclusive date bounds for a non-empty canonical frame."""

    if frame.empty:
        raise ValueError("cannot compute date bounds for an empty frame")
    dates = pd.to_datetime(frame["date"]).dt.date
    return cast(date, dates.min()), cast(date, dates.max())
