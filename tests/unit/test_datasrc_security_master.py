from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from yquant.datasrc.repo import LocalDataRepo
from yquant.datasrc.security_master import (
    canonicalize_security_master,
    listed_symbols_on,
    security_master_from_records,
)


def _master() -> pd.DataFrame:
    return security_master_from_records(
        [
            {"symbol": "aapl", "market": "us", "listing_date": "1980-12-12"},
            {"symbol": "msft", "market": "us", "listing_date": "1986-03-13"},
            # Delisted name: tradable in 2019, gone by 2021.
            {
                "symbol": "deadco",
                "market": "us",
                "listing_date": "2015-01-05",
                "delisting_date": "2020-06-30",
            },
            # Lists in the future relative to the 2019 query.
            {"symbol": "newco", "market": "us", "listing_date": "2023-09-01"},
        ]
    )


def test_canonicalize_requires_listing_date() -> None:
    with pytest.raises(ValueError, match="listing_date"):
        canonicalize_security_master(
            pd.DataFrame({"symbol": ["AAPL"], "market": ["us"], "listing_date": [None]})
        )


def test_listed_symbols_includes_later_delisted_names() -> None:
    universe = listed_symbols_on(_master(), date(2019, 6, 30))
    assert universe == ["AAPL", "DEADCO", "MSFT"]  # DEADCO still alive, NEWCO not yet listed


def test_listed_symbols_excludes_delisted_after_delisting() -> None:
    universe = listed_symbols_on(_master(), date(2021, 1, 4))
    assert universe == ["AAPL", "MSFT"]  # DEADCO delisted 2020-06-30


def test_delisting_boundary_is_exclusive_on_delisting_day() -> None:
    # On the delisting date itself the name is treated as no longer tradable.
    assert "DEADCO" not in listed_symbols_on(_master(), date(2020, 6, 30))
    assert "DEADCO" in listed_symbols_on(_master(), date(2020, 6, 29))


def test_repo_get_universe_prefers_security_master(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_security_master(_master())

    assert repo.get_universe(date(2019, 6, 30)) == ["AAPL", "DEADCO", "MSFT"]
    assert repo.get_universe(date(2024, 1, 2)) == ["AAPL", "MSFT", "NEWCO"]


def test_repo_get_universe_falls_back_to_bar_presence(tmp_path: Path) -> None:
    from yquant.datasrc.bars import make_daily_bars_frame

    repo = LocalDataRepo(tmp_path)
    bars = make_daily_bars_frame(
        symbol="AAPL",
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-02"])),
        raw_open=pd.Series([100.0]),
        raw_high=pd.Series([101.0]),
        raw_low=pd.Series([99.0]),
        raw_close=pd.Series([100.5]),
        volume=pd.Series([1000]),
        source="yfinance",
    )
    repo.write_daily_bars(bars)

    # No security master written -> bar-presence fallback.
    assert repo.get_universe(date(2024, 1, 2)) == ["AAPL"]
