"""Protocols for external market data sources and the read repository (03 §5.1)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    import pandas as pd


class DataSource(Protocol):
    """Unified protocol implemented by every external data adapter."""

    name: str

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch daily OHLCV bars for one symbol."""

    def fetch_stock_list(self, include_delisted: bool = True) -> pd.DataFrame:
        """Fetch stock master data."""

    def fetch_announcements(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch announcements for one symbol."""


class DataRepo(Protocol):
    """The single read entry point for business modules (03 §5.1).

    Business code (strategies, risk engine, backtest) only ever imports this
    protocol, never a raw source. Concrete implementation (Parquet + SQLite)
    lands with M1; strategies and the risk engine are written against the
    protocol so they can be unit-tested with a synthetic repo.
    """

    def get_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adjust: Literal["none", "adjusted"] = "adjusted",
    ) -> pd.DataFrame:
        """Return daily bars for ``symbols`` in ``[start, end]``.

        Columns: symbol, market, date, open, high, low, close, volume, amount,
        adj_factor, is_halted, halt_reason, session. Rows are aligned to each
        market's trading calendar; ``adjust="adjusted"`` back-adjusts price for
        splits/dividends.
        """

    def get_universe(
        self,
        on_date: date,
        market: Literal["us", "all"] = "all",
    ) -> list[str]:
        """Return the symbols listed and alive on ``on_date`` (survivorship-safe)."""
