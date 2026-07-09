"""Golden dataset: frozen, deterministic bars for regression + drills (06 §4).

The four historical windows the plan mandates — 2020-01~06 (COVID crash),
2022 full year (rate-hike drawdown), 2023-02~05 (SVB), 2024-07~09 (yen carry) —
are reconstructed as a *synthetic but frozen* dataset. Prices are a pure function
of ``(symbol, date)`` via SHA-256, so the content hash is stable across machines
and can be committed to the manifest (only-append errata). This gives the
regression suite and the historical-event drills a shared, reproducible base
without shipping licensed vendor history.

Determinism, not realism, is the contract: each window carries a characteristic
market drift/vol so the drills exercise the regime machinery, but nothing here is
a performance claim (drills are ``contaminated`` by construction, 06 §5).
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from yquant.datasrc.bars import canonicalize_daily_bars
from yquant.datasrc.manifest import DataManifest, build_manifest, dataframe_content_hash

# SPY/QQQ/IWM + GICS 11 sectors + bond/gold/commodity pool + 30 synthetic names.
_INDEX_ETFS: tuple[str, ...] = ("SPY", "QQQ", "IWM")
_SECTOR_ETFS: tuple[str, ...] = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)
_MACRO_POOL: tuple[str, ...] = ("TLT", "IEF", "GLD", "DBC", "BIL")
_STOCKS: tuple[str, ...] = tuple(f"STK{i:02d}" for i in range(1, 31))

GOLDEN_UNIVERSE: tuple[str, ...] = (*_INDEX_ETFS, *_SECTOR_ETFS, *_MACRO_POOL, *_STOCKS)

# Frozen as-of timestamp so the manifest / content hash never drift on the clock.
_GOLDEN_ASOF = datetime(2025, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class GoldenWindow:
    """One frozen regression / drill window (inclusive dates)."""

    key: str
    label: str
    start: date
    end: date
    # Characteristic daily market drift and volatility for the window.
    market_drift: float
    market_vol: float


GOLDEN_WINDOWS: tuple[GoldenWindow, ...] = (
    GoldenWindow(
        key="2020_covid",
        label="2020-01~2020-06 COVID crash + V-recovery",
        start=date(2020, 1, 1),
        end=date(2020, 6, 30),
        market_drift=-0.0018,
        market_vol=0.028,
    ),
    GoldenWindow(
        key="2022_hikes",
        label="2022 full-year rate-hike drawdown",
        start=date(2022, 1, 1),
        end=date(2022, 12, 31),
        market_drift=-0.0009,
        market_vol=0.016,
    ),
    GoldenWindow(
        key="2023_svb",
        label="2023-02~2023-05 SVB banking stress",
        start=date(2023, 2, 1),
        end=date(2023, 5, 31),
        market_drift=-0.0004,
        market_vol=0.014,
    ),
    GoldenWindow(
        key="2024_carry",
        label="2024-07~2024-09 yen carry unwind",
        start=date(2024, 7, 1),
        end=date(2024, 9, 30),
        market_drift=-0.0002,
        market_vol=0.013,
    ),
)

_WINDOWS_BY_KEY = {w.key: w for w in GOLDEN_WINDOWS}


def get_window(key: str) -> GoldenWindow:
    """Look up a golden window by key, raising a clear error if unknown."""

    try:
        return _WINDOWS_BY_KEY[key]
    except KeyError:
        known = ", ".join(sorted(_WINDOWS_BY_KEY))
        raise KeyError(f"unknown golden window {key!r}; known: {known}") from None


def _business_days(start: date, end: date) -> list[date]:
    """Mon-Fri sessions in [start, end]; a deterministic proxy for the calendar."""

    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _unit_noise(symbol: str, day: date, salt: str) -> float:
    """A deterministic value in [-1, 1] from ``(symbol, date, salt)`` via SHA-256."""

    key = f"{symbol}|{day.isoformat()}|{salt}".encode()
    digest = hashlib.sha256(key).digest()
    (raw,) = struct.unpack(">Q", digest[:8])
    return float(raw / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0


def _symbol_beta(symbol: str) -> float:
    """Stable per-symbol sensitivity to the market drift, in ~[0.5, 1.5]."""

    return 0.5 + (_unit_noise(symbol, date(2000, 1, 1), "beta") + 1.0) / 2.0


def _base_price(symbol: str) -> float:
    """Stable per-symbol starting price in ~[20, 320]."""

    return 20.0 + (_unit_noise(symbol, date(2000, 1, 1), "base") + 1.0) / 2.0 * 300.0


def _symbol_closes(symbol: str, window: GoldenWindow, days: list[date]) -> list[float]:
    """Compound a deterministic daily return path for one symbol in a window."""

    beta = _symbol_beta(symbol)
    price = _base_price(symbol)
    closes: list[float] = []
    for day in days:
        idio = _unit_noise(symbol, day, window.key) * window.market_vol
        ret = beta * window.market_drift + idio
        price = max(1.0, price * (1.0 + ret))
        closes.append(round(price, 4))
    return closes


def build_golden_bars(window_key: str) -> pd.DataFrame:
    """Build the canonical daily-bar frame for one frozen window.

    Returns the storage-schema frame (``close_raw`` etc.), so callers can take a
    :func:`~yquant.datasrc.bars.repo_view` for the engine or reconcile two source
    slices directly. ``adj_factor`` is 1.0 (no golden splits; the P4 continuity
    check ships its own split fixture).
    """

    window = get_window(window_key)
    days = _business_days(window.start, window.end)
    frames: list[pd.DataFrame] = []
    for symbol in GOLDEN_UNIVERSE:
        closes = _symbol_closes(symbol, window, days)
        close = pd.Series(closes)
        prev = close.shift(1).fillna(close)
        high = pd.concat([prev, close], axis=1).max(axis=1) * 1.004
        low = pd.concat([prev, close], axis=1).min(axis=1) * 0.996
        volume = pd.Series(
            [1_000_000 + int(abs(_unit_noise(symbol, d, "vol")) * 500_000) for d in days]
        )
        frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "market": "us",
                    "date": pd.Series(days),
                    "open_raw": prev.round(4),
                    "high_raw": high.round(4),
                    "low_raw": low.round(4),
                    "close_raw": close,
                    "open_adjusted": prev.round(4),
                    "high_adjusted": high.round(4),
                    "low_adjusted": low.round(4),
                    "close_adjusted": close,
                    "volume": volume,
                    "amount": (close * volume).round(2),
                    "adj_factor": 1.0,
                    "is_halted": False,
                    "halt_reason": "",
                    "session": "regular",
                    "source": "golden",
                    "asof": _GOLDEN_ASOF,
                }
            )
        )
    combined = pd.concat(frames, ignore_index=True)
    return canonicalize_daily_bars(combined)


def golden_content_hash(window_key: str) -> str:
    """Stable content hash of a window's frozen bars (goes into the manifest)."""

    return dataframe_content_hash(build_golden_bars(window_key))


def golden_manifest(window_key: str) -> DataManifest:
    """Build a content-addressed manifest record for a frozen golden window."""

    window = get_window(window_key)
    bars = build_golden_bars(window_key)
    return build_manifest(
        bars,
        dataset=f"golden:{window.key}",
        source="golden",
        storage_path=f"golden/{window.key}.parquet",
        created_at_utc=_GOLDEN_ASOF,
    )
