"""Protocols for external market data sources."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

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
