from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.repo import LocalDataRepo


def _bars(asof: datetime, closes: tuple[float, float], symbol: str = "AAPL") -> pd.DataFrame:
    close = pd.Series(list(closes))
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"])),
        raw_open=close - 0.5,
        raw_high=close + 1.0,
        raw_low=close - 1.0,
        raw_close=close,
        volume=pd.Series([1_000, 1_100]),
        source="yfinance",
        asof=asof,
    )


def test_asof_excludes_rows_recorded_after_cutoff(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_bars(datetime(2024, 1, 4, tzinfo=UTC), (100.0, 102.0)))

    # Cutoff before the data was recorded -> nothing visible.
    early = repo.get_bars_asof(
        ["AAPL"], date(2024, 1, 1), date(2024, 1, 31), datetime(2024, 1, 3, tzinfo=UTC)
    )
    assert early.empty

    # Cutoff after the record -> visible.
    late = repo.get_bars_asof(
        ["AAPL"], date(2024, 1, 1), date(2024, 1, 31), datetime(2024, 1, 5, tzinfo=UTC)
    )
    assert list(late["close"]) == [100.0, 102.0]


def test_asof_shows_only_symbols_recorded_by_cutoff(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    # AAPL arrives early; MSFT's bars are only recorded a week later.
    repo.write_daily_bars(_bars(datetime(2024, 1, 4, tzinfo=UTC), (100.0, 102.0), symbol="AAPL"))
    repo.write_daily_bars(_bars(datetime(2024, 1, 10, tzinfo=UTC), (300.0, 305.0), symbol="MSFT"))

    view = repo.get_bars_asof(
        ["AAPL", "MSFT"], date(2024, 1, 1), date(2024, 1, 31), datetime(2024, 1, 5, tzinfo=UTC)
    )
    assert set(view["symbol"]) == {"AAPL"}  # MSFT not yet recorded at the cutoff


def test_asof_accepts_naive_cutoff_as_utc(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_bars(datetime(2024, 1, 4, tzinfo=UTC), (100.0, 102.0)))

    view = repo.get_bars_asof(
        ["AAPL"], date(2024, 1, 1), date(2024, 1, 31), datetime(2024, 1, 5)
    )
    assert not view.empty


def test_asof_reconstructs_value_before_later_revision(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_bars(datetime(2024, 1, 4, tzinfo=UTC), (100.0, 102.0)))
    repo.write_daily_bars(_bars(datetime(2024, 1, 10, tzinfo=UTC), (101.0, 103.0)))

    historical = repo.get_bars_asof(
        ["AAPL"],
        date(2024, 1, 1),
        date(2024, 1, 31),
        datetime(2024, 1, 5, tzinfo=UTC),
    )
    current = repo.get_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))

    assert list(historical["close"]) == [100.0, 102.0]
    assert list(current["close"]) == [101.0, 103.0]
