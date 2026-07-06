"""External daily-bar adapters for M1."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import date, timedelta
from types import ModuleType
from typing import Any, cast

import pandas as pd

from yquant.datasrc.bars import make_daily_bars_frame


class YFinanceDailyBarSource:
    """Primary US daily-bar source using yfinance."""

    name = "yfinance"

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        yfinance = importlib.import_module("yfinance")
        download = _required_callable(yfinance, "download")
        raw = download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            progress=False,
        )
        return normalize_yfinance_daily_bars(raw, symbol)

    def fetch_stock_list(self, include_delisted: bool = True) -> pd.DataFrame:
        raise NotImplementedError("yfinance stock-list adapter is not part of M1 daily bars yet")

    def fetch_announcements(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError("EDGAR adapter owns announcements")


class StooqDailyBarSource:
    """Backup US daily-bar source using pandas-datareader's Stooq reader."""

    name = "stooq"

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        importlib.import_module("pandas_datareader")
        reader = importlib.import_module("pandas_datareader.data")
        data_reader = _required_callable(reader, "DataReader")
        raw = data_reader(symbol, "stooq", start=start, end=end)
        return normalize_stooq_daily_bars(raw, symbol)

    def fetch_stock_list(self, include_delisted: bool = True) -> pd.DataFrame:
        raise NotImplementedError("Stooq stock-list adapter is not part of M1 daily bars yet")

    def fetch_announcements(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError("EDGAR adapter owns announcements")


def normalize_yfinance_daily_bars(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize yfinance output with raw and adjusted prices dual-stored."""

    source = _prepare_source_frame(frame)
    raw_open = _column(source, "Open")
    raw_high = _column(source, "High")
    raw_low = _column(source, "Low")
    raw_close = _column(source, "Close")
    adj_close = _optional_column(source, "Adj Close")
    volume = _column(source, "Volume")

    factor = adj_close / raw_close if adj_close is not None else pd.Series(1.0, index=source.index)
    factor = factor.replace([float("inf"), float("-inf")], pd.NA).fillna(1.0)
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=_date_column(source),
        raw_open=raw_open,
        raw_high=raw_high,
        raw_low=raw_low,
        raw_close=raw_close,
        volume=volume,
        source="yfinance",
        adj_factor=factor,
    )


def normalize_stooq_daily_bars(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize Stooq output. Stooq bars are treated as raw, unadjusted bars."""

    source = _prepare_source_frame(frame)
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=_date_column(source),
        raw_open=_column(source, "Open"),
        raw_high=_column(source, "High"),
        raw_low=_column(source, "Low"),
        raw_close=_column(source, "Close"),
        volume=_column(source, "Volume"),
        source="stooq",
        adj_factor=pd.Series(1.0, index=source.index),
    )


def _prepare_source_frame(frame: pd.DataFrame) -> pd.DataFrame:
    source = frame.copy()
    source.columns = [_flatten_column(column) for column in source.columns]
    if "Date" not in source.columns:
        source = source.reset_index()
        source.columns = [_flatten_column(column) for column in source.columns]
    return cast(pd.DataFrame, source)


def _flatten_column(column: Any) -> str:
    if isinstance(column, tuple):
        return "_".join(str(part) for part in column if str(part))
    return str(column)


def _date_column(frame: pd.DataFrame) -> pd.Series:
    column = _column(frame, "Date")
    return cast(pd.Series, pd.to_datetime(column).dt.date)


def _column(frame: pd.DataFrame, wanted: str) -> pd.Series:
    normalized_wanted = _normalize_name(wanted)
    for column in frame.columns:
        name = str(column)
        normalized = _normalize_name(name)
        if normalized == normalized_wanted or normalized.startswith(f"{normalized_wanted}_"):
            return cast(pd.Series, frame[name])
    raise ValueError(f"source frame missing required column: {wanted}")


def _optional_column(frame: pd.DataFrame, wanted: str) -> pd.Series | None:
    try:
        return _column(frame, wanted)
    except ValueError:
        return None


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _required_callable(module: ModuleType, name: str) -> Callable[..., Any]:
    value = getattr(module, name)
    if not callable(value):
        raise TypeError(f"{module.__name__}.{name} is not callable")
    return cast(Callable[..., Any], value)
