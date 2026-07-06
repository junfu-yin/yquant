"""Data-integrity traps: the pipeline must refuse or prevent bad data.

These assert the system's defensive guarantees (03 quality bar): no invalid OHLC
accepted, no future-recorded data leaked into a point-in-time read, delisted
names preserved in past universes, deterministic upserts, and faithful
adjustment factors.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.quality import check_daily_bars
from yquant.datasrc.repo import LocalDataRepo
from yquant.datasrc.security_master import listed_symbols_on, security_master_from_records


def _bars(symbol: str, closes: tuple[float, ...], asof: datetime, source: str = "yfinance",
          factor: float = 1.0) -> pd.DataFrame:
    close = pd.Series(list(closes))
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(pd.date_range("2024-01-02", periods=len(closes), freq="D")),
        raw_open=close,
        raw_high=close + 1.0,
        raw_low=close - 1.0,
        raw_close=close,
        volume=pd.Series([1_000] * len(closes)),
        source=source,
        adj_factor=pd.Series([factor] * len(closes)),
        asof=asof,
    )


def test_t16_quality_gate_rejects_close_outside_high_low() -> None:
    """T16: a bar whose close is above its high must be rejected, not stored."""

    bad = make_daily_bars_frame(
        symbol="AAPL",
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-02"])),
        raw_open=pd.Series([100.0]),
        raw_high=pd.Series([101.0]),
        raw_low=pd.Series([99.0]),
        raw_close=pd.Series([500.0]),  # close >> high
        volume=pd.Series([1_000]),
        source="yfinance",
    )
    with pytest.raises(ValueError, match="quality"):
        check_daily_bars(bad).raise_for_errors()


def test_t17_asof_read_never_leaks_future_recorded_rows(tmp_path: Path) -> None:
    """T17: data recorded after the decision instant must be invisible."""

    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_bars("AAPL", (100.0, 102.0), datetime(2024, 1, 10, tzinfo=UTC)))

    leaked = repo.get_bars_asof(
        ["AAPL"], date(2024, 1, 1), date(2024, 1, 31), datetime(2024, 1, 5, tzinfo=UTC)
    )
    assert leaked.empty  # recorded Jan 10, invisible as of Jan 5


def test_t18_past_universe_keeps_delisted_name() -> None:
    """T18: a name delisted later must still appear in a past universe."""

    master = security_master_from_records(
        [
            {"symbol": "DEADCO", "market": "us", "listing_date": "2015-01-05",
             "delisting_date": "2020-06-30"},
        ]
    )
    assert "DEADCO" in listed_symbols_on(master, date(2019, 6, 30))
    assert "DEADCO" not in listed_symbols_on(master, date(2021, 1, 4))


def test_t19_upsert_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    """T19: writing the same slice twice must not duplicate or reorder rows."""

    repo = LocalDataRepo(tmp_path)
    frame = _bars("AAPL", (100.0, 102.0), datetime(2024, 1, 4, tzinfo=UTC))
    repo.write_daily_bars(frame)
    first = repo.get_daily_bars_storage(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))
    repo.write_daily_bars(frame)
    second = repo.get_daily_bars_storage(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))

    assert len(first) == len(second) == 2
    pd.testing.assert_frame_equal(
        first.reset_index(drop=True), second.reset_index(drop=True)
    )


def test_t20_adjustment_factor_is_applied_to_adjusted_view(tmp_path: Path) -> None:
    """T20: adjusted close must equal raw close times the stored factor."""

    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_bars("AAPL", (100.0, 200.0), datetime(2024, 1, 4, tzinfo=UTC),
                                factor=0.5))
    adjusted = repo.get_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31), adjust="adjusted")
    raw = repo.get_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31), adjust="none")

    assert list(adjusted["close"]) == [50.0, 100.0]
    assert list(raw["close"]) == [100.0, 200.0]
