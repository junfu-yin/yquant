"""Point-in-time security master for survivorship-safe universes.

Bar-presence is not survivorship-safe: a delisted name simply vanishes from the
data, so a universe rebuilt from bars silently drops losers. The security master
records listing and delisting dates so ``get_universe(on_date)`` can answer "what
was actually tradable on this date" — including names that later delisted.
"""

from __future__ import annotations

from datetime import date
from typing import cast

import pandas as pd

from yquant.datasrc.bars import utc_now

SECURITY_MASTER_COLUMNS: tuple[str, ...] = (
    "symbol",
    "market",
    "listing_date",
    "delisting_date",
    "asof",
)


def canonicalize_security_master(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a typed security-master frame in the canonical schema.

    ``delisting_date`` is nullable (a still-listed security has ``NaT``). Rows are
    de-duplicated per symbol keeping the most recent ``asof``.
    """

    missing = [column for column in ("symbol", "market", "listing_date") if column not in frame]
    if missing:
        raise ValueError(f"security master missing required columns: {missing}")

    out = frame.copy()
    if "delisting_date" not in out.columns:
        out["delisting_date"] = pd.NaT
    if "asof" not in out.columns:
        out["asof"] = utc_now()

    out = out.loc[:, list(SECURITY_MASTER_COLUMNS)].copy()
    out["symbol"] = out["symbol"].astype("string").str.strip().str.upper()
    out["market"] = out["market"].astype("string").str.strip().str.lower()
    out["listing_date"] = _to_date(out["listing_date"])
    out["delisting_date"] = _to_optional_date(out["delisting_date"])
    out["asof"] = pd.to_datetime(out["asof"], utc=True)

    if out["listing_date"].isna().any():
        raise ValueError("security master rows must all have a listing_date")

    out = out.sort_values(["symbol", "asof"]).drop_duplicates(["symbol"], keep="last")
    out = out.sort_values(["symbol"]).reset_index(drop=True)
    return cast(pd.DataFrame, out)


def listed_symbols_on(
    frame: pd.DataFrame,
    on_date: date,
    *,
    market: str | None = None,
) -> list[str]:
    """Symbols listed on or before ``on_date`` and not yet delisted by then."""

    if frame.empty:
        return []
    master = canonicalize_security_master(frame)
    listed = master["listing_date"] <= on_date
    not_delisted = master["delisting_date"].isna() | (master["delisting_date"] > on_date)
    mask = listed & not_delisted
    if market is not None:
        mask &= master["market"].astype(str) == market.strip().lower()
    symbols = master.loc[mask, "symbol"].astype(str).tolist()
    return sorted(set(symbols))


def security_master_from_records(records: list[dict[str, object]]) -> pd.DataFrame:
    """Build a canonical security master from plain dict rows (e.g. CSV rows)."""

    return canonicalize_security_master(pd.DataFrame.from_records(records))


def _to_date(series: pd.Series) -> pd.Series:
    return cast(pd.Series, pd.to_datetime(series, errors="coerce").dt.date)


def _to_optional_date(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    return cast(pd.Series, parsed.apply(lambda value: value.date() if pd.notna(value) else None))


def empty_security_master() -> pd.DataFrame:
    frame = pd.DataFrame(columns=list(SECURITY_MASTER_COLUMNS))
    frame["asof"] = pd.to_datetime(frame["asof"], utc=True)
    return frame
