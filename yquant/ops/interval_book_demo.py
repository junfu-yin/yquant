"""A deterministic interval-book demo instance (`yquant ops interval-book`).

Builds several years of frozen daily bars for the C1 asset pool (via the same
SHA-256 price mechanism the golden dataset uses, so it is reproducible across
machines) and runs the real walk-forward → interval-book pipeline. This is the
"分层区间书模板+基于 C1–C3/S-A 的首份实例" deliverable: a signed template with a
first, honestly-derived instance, LLM-free and replay-able.

Nothing here is a performance claim — the bars are synthetic — but the *shape*
(core numeric band from OOS percentiles, satellite-LLM/overlay ``observing``)
is exactly what the L3 signing ceremony produces on real history.
"""

from __future__ import annotations

import hashlib
import struct
from datetime import date, timedelta

import pandas as pd

from yquant.datasrc.bars import repo_view
from yquant.ops.interval_book import IntervalBook, build_interval_book
from yquant.strategies.core.c1_multiasset_dualmom import DEFAULT_ASSET_POOL

_DEMO_ASOF = date(2025, 1, 1)
_POOL: tuple[str, ...] = tuple(sleeve.etf for sleeve in DEFAULT_ASSET_POOL)


def _unit_noise(symbol: str, day: date, salt: str) -> float:
    key = f"{symbol}|{day.isoformat()}|{salt}".encode()
    (raw,) = struct.unpack(">Q", hashlib.sha256(key).digest()[:8])
    return float(raw / 0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0


def _business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def build_demo_bars(*, start: date = date(2016, 1, 1), years: int = 8) -> pd.DataFrame:
    """Several years of frozen daily closes for the C1 pool, gently trending."""

    end = date(start.year + years, start.month, start.day) - timedelta(days=1)
    days = _business_days(start, end)
    frames: list[pd.DataFrame] = []
    for i, symbol in enumerate(_POOL):
        base = 40.0 + i * 20.0
        drift = 0.0003 + 0.00005 * i  # each sleeve a distinct, positive drift.
        closes: list[float] = []
        price = base
        for day in days:
            idio = _unit_noise(symbol, day, "iv") * 0.012
            price = max(1.0, price * (1.0 + drift + idio))
            closes.append(round(price, 4))
        close = pd.Series(closes)
        prev = close.shift(1).fillna(close)
        frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "market": "us",
                    "date": pd.Series(days),
                    "open_raw": prev.round(4),
                    "high_raw": (close * 1.004).round(4),
                    "low_raw": (close * 0.996).round(4),
                    "close_raw": close,
                    "open_adjusted": prev.round(4),
                    "high_adjusted": (close * 1.004).round(4),
                    "low_adjusted": (close * 0.996).round(4),
                    "close_adjusted": close,
                    "volume": 1_000_000,
                    "amount": (close * 1_000_000).round(2),
                    "adj_factor": 1.0,
                    "is_halted": False,
                    "halt_reason": "",
                    "session": "regular",
                    "source": "ops_demo",
                    "asof": pd.Timestamp(_DEMO_ASOF, tz="UTC"),
                }
            )
        )
    return repo_view(pd.concat(frames, ignore_index=True), adjust="adjusted")


def build_demo_interval_book() -> IntervalBook:
    """The first interval-book instance over frozen multi-year demo bars."""

    bars = build_demo_bars()
    return build_interval_book(bars, as_of=_DEMO_ASOF, initial_cash=50_000.0)
