from __future__ import annotations

import sys
import types
from datetime import date

import pandas as pd
import pytest

from yquant.datasrc.adapters import (
    NasdaqDailyBarSource,
    StooqDailyBarSource,
    YFinanceDailyBarSource,
    normalize_nasdaq_daily_bars,
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


def test_normalize_nasdaq_cleans_numbers_and_sorts_ascending() -> None:
    raw = pd.DataFrame(
        [
            {
                "date": "07/10/2026",
                "close": "$315.32",
                "volume": "34,132,320",
                "open": "$314.72",
                "high": "$316.91",
                "low": "$312.17",
            },
            {
                "date": "07/09/2026",
                "close": "$316.22",
                "volume": "48,124,490",
                "open": "$310.51",
                "high": "$316.53",
                "low": "$308.16",
            },
        ]
    )

    out = normalize_nasdaq_daily_bars(raw, "aapl")

    assert out["date"].tolist() == [date(2026, 7, 9), date(2026, 7, 10)]
    assert out["close_raw"].tolist() == [316.22, 315.32]
    assert out["volume"].tolist() == [48_124_490, 34_132_320]
    assert set(out["source"]) == {"nasdaq"}


def test_normalize_nasdaq_empty_rows_returns_canonical_empty_frame() -> None:
    out = normalize_nasdaq_daily_bars(pd.DataFrame(), "AAPL")
    assert out.empty
    assert "close_raw" in out.columns


def test_normalize_nasdaq_missing_column_raises() -> None:
    raw = pd.DataFrame(
        [{"date": "07/10/2026", "open": "$1", "high": "$2", "low": "$1"}]
    )
    with pytest.raises(ValueError, match="missing required columns"):
        normalize_nasdaq_daily_bars(raw, "AAPL")


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


def test_nasdaq_source_fetches_via_mocked_http(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    payload = {
        "data": {
            "tradesTable": {
                "rows": [
                    {
                        "date": "07/10/2026",
                        "close": "$315.32",
                        "volume": "34,132,320",
                        "open": "$314.72",
                        "high": "$316.91",
                        "low": "$312.17",
                    }
                ]
            }
        },
        "status": {"rCode": 200},
    }

    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return payload

    def _get(url: str, **kwargs: object) -> Response:
        captured.update({"url": url, **kwargs})
        return Response()

    fake = types.ModuleType("requests")
    fake.get = _get  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "requests", fake)

    out = NasdaqDailyBarSource().fetch_daily_bars(
        "aapl", date(2026, 7, 1), date(2026, 7, 10)
    )

    assert str(captured["url"]).endswith("/AAPL/historical")
    assert captured["timeout"] == 30
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["fromdate"] == "2026-07-01"
    assert params["todate"] == "2026-07-10"
    assert out["source"].iloc[0] == "nasdaq"


def test_nasdaq_source_surfaces_api_level_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "data": None,
                "status": {
                    "rCode": 400,
                    "bCodeMessage": [{"errorMessage": "bad date"}],
                },
            }

    fake = types.ModuleType("requests")
    fake.get = lambda *args, **kwargs: Response()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "requests", fake)

    with pytest.raises(ValueError, match="bad date"):
        NasdaqDailyBarSource().fetch_daily_bars(
            "AAPL", date(2026, 7, 1), date(2026, 7, 10)
        )


def test_nasdaq_source_surfaces_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 429

        def json(self) -> dict[str, object]:
            return {}

    fake = types.ModuleType("requests")
    fake.get = lambda *args, **kwargs: Response()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "requests", fake)

    with pytest.raises(RuntimeError, match="HTTP 429"):
        NasdaqDailyBarSource().fetch_daily_bars(
            "AAPL", date(2026, 7, 1), date(2026, 7, 10)
        )


def test_adapters_unimplemented_methods_raise() -> None:
    for source in (YFinanceDailyBarSource(), NasdaqDailyBarSource(), StooqDailyBarSource()):
        with pytest.raises(NotImplementedError):
            source.fetch_stock_list()
        with pytest.raises(NotImplementedError):
            source.fetch_announcements("AAPL", date(2024, 1, 1), date(2024, 1, 2))
