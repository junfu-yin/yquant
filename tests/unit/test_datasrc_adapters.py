from __future__ import annotations

import sys
import types
from datetime import date

import pandas as pd
import pytest

from yquant.datasrc.adapters import (
    StooqDailyBarSource,
    YFinanceDailyBarSource,
    normalize_stooq_daily_bars,
    normalize_yfinance_daily_bars,
)


def _yf_single_index() -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03"]), name="Date")
    return pd.DataFrame(
        {
            "Open": [99.0, 101.0],
            "High": [101.0, 103.0],
            "Low": [98.0, 100.0],
            "Close": [100.0, 102.0],
            "Adj Close": [50.0, 51.0],
            "Volume": [1_000, 1_100],
        },
        index=idx,
    )


def test_normalize_yfinance_applies_adjustment_factor() -> None:
    out = normalize_yfinance_daily_bars(_yf_single_index(), "AAPL")
    # Adj Close is half of Close, so adj factor 0.5 -> adjusted close = raw * 0.5.
    assert out["close_raw"].tolist() == [100.0, 102.0]
    assert out["close_adjusted"].tolist() == [50.0, 51.0]


def test_normalize_yfinance_without_adj_close_uses_unit_factor() -> None:
    raw = _yf_single_index().drop(columns=["Adj Close"])
    out = normalize_yfinance_daily_bars(raw, "AAPL")
    assert out["close_adjusted"].tolist() == out["close_raw"].tolist()
    assert out["adj_factor"].tolist() == [1.0, 1.0]


def test_normalize_yfinance_handles_multiindex_columns() -> None:
    idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]), name="Date")
    cols = pd.MultiIndex.from_tuples(
        [
            ("Open", "AAPL"),
            ("High", "AAPL"),
            ("Low", "AAPL"),
            ("Close", "AAPL"),
            ("Adj Close", "AAPL"),
            ("Volume", "AAPL"),
        ]
    )
    raw = pd.DataFrame([[99.0, 101.0, 98.0, 100.0, 100.0, 1_000]], index=idx, columns=cols)
    out = normalize_yfinance_daily_bars(raw, "AAPL")
    assert out["symbol"].iloc[0] == "AAPL"
    assert out["close_raw"].iloc[0] == 100.0


def test_normalize_stooq_is_unadjusted() -> None:
    idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]), name="Date")
    raw = pd.DataFrame(
        {"Open": [99.0], "High": [101.0], "Low": [98.0], "Close": [100.0], "Volume": [1_000]},
        index=idx,
    )
    out = normalize_stooq_daily_bars(raw, "AAPL")
    assert out["adj_factor"].iloc[0] == 1.0
    assert out["close_adjusted"].iloc[0] == out["close_raw"].iloc[0]


def test_normalize_missing_column_raises() -> None:
    idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]), name="Date")
    raw = pd.DataFrame({"Open": [99.0]}, index=idx)  # no High/Low/Close/Volume
    with pytest.raises(ValueError, match="missing required column"):
        normalize_stooq_daily_bars(raw, "AAPL")


def test_yfinance_source_fetches_via_mocked_module(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _download(symbol: str, **kwargs: object) -> pd.DataFrame:
        captured.update({"symbol": symbol, **kwargs})
        return _yf_single_index()

    fake = types.ModuleType("yfinance")
    fake.download = _download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    out = YFinanceDailyBarSource().fetch_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 3))
    assert out["symbol"].iloc[0] == "AAPL"
    assert captured["auto_adjust"] is False  # raw + adj stored separately


def test_stooq_source_fetches_via_mocked_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]), name="Date")
    frame = pd.DataFrame(
        {"Open": [99.0], "High": [101.0], "Low": [98.0], "Close": [100.0], "Volume": [1_000]},
        index=idx,
    )

    pdr = types.ModuleType("pandas_datareader")
    pdr_data = types.ModuleType("pandas_datareader.data")
    pdr_data.DataReader = lambda *a, **k: frame  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pandas_datareader", pdr)
    monkeypatch.setitem(sys.modules, "pandas_datareader.data", pdr_data)

    out = StooqDailyBarSource().fetch_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 15))
    assert out["source"].iloc[0] == "stooq"


def test_adapters_unimplemented_methods_raise() -> None:
    for source in (YFinanceDailyBarSource(), StooqDailyBarSource()):
        with pytest.raises(NotImplementedError):
            source.fetch_stock_list()
        with pytest.raises(NotImplementedError):
            source.fetch_announcements("AAPL", date(2024, 1, 1), date(2024, 1, 2))
