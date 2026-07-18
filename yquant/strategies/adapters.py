"""Repo → strategy-series adapters and backtest target providers (03 §5.3).

The rule strategies (C1 dual momentum, S-A sector momentum) are pure functions
over month-end close series, and the backtest engine drives a
:class:`~yquant.backtest.engine.TargetProvider` that only sees *today's* closes.
This module bridges the two: it resamples daily bars to month-end closes and
wraps a strategy's pure ``weights`` function into a causal, monthly-rebalancing
provider.

Everything here is a pure function of the bars passed in — no wall-clock reads,
no randomness — so a walk-forward run reproduces bit-for-bit (07 replay).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from yquant.strategies.base import TargetPortfolio
from yquant.strategies.core.c1_multiasset_dualmom import DEFAULT_ASSET_POOL, dual_momentum_weights
from yquant.strategies.satellite.s_a_sector_momentum import (
    GICS_SECTOR_ETFS,
    sector_momentum_weights,
)

if TYPE_CHECKING:
    from yquant.backtest.engine import TargetProvider
    from yquant.datasrc.protocols import DataRepo

# Dual momentum needs 12-1 momentum, so 14 month-end closes is the floor.
DEFAULT_MIN_HISTORY = 14


def resample_to_month_end(bars: pd.DataFrame) -> dict[str, list[tuple[date, float]]]:
    """Collapse daily bars to one (month-end date, close) per calendar month.

    Returns ``symbol -> [(month_end_date, close), ...]`` ordered oldest→newest.
    The month-end close is the last available close in that calendar month, so
    a mid-month ``as_of`` still contributes the latest known price for the month.
    """

    if bars.empty:
        return {}
    frame = bars.loc[:, ["symbol", "date", "close"]].copy()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date

    out: dict[str, list[tuple[date, float]]] = {}
    for symbol, group in frame.groupby("symbol", sort=True):
        group = group.sort_values("date")
        by_month: dict[tuple[int, int], tuple[date, float]] = {}
        for day, close in zip(group["date"], group["close"], strict=True):
            if pd.isna(close):
                continue
            by_month[(day.year, day.month)] = (day, float(close))  # last close wins
        out[str(symbol)] = [by_month[key] for key in sorted(by_month)]
    return out


def month_end_trading_dates(bars: pd.DataFrame) -> set[date]:
    """Return the last trading date of each calendar month present in ``bars``."""

    if bars.empty:
        return set()
    days = pd.to_datetime(bars["date"]).dt.date
    last_of_month: dict[tuple[int, int], date] = {}
    for day in days:
        key = (day.year, day.month)
        last_of_month[key] = max(last_of_month.get(key, day), day)
    return set(last_of_month.values())


def monthly_closes_from_repo(
    repo: DataRepo,
    symbols: Sequence[str],
    as_of: date,
    lookback_months: int = DEFAULT_MIN_HISTORY,
) -> dict[str, list[float]]:
    """Fetch adjusted bars and resample to the last ``lookback_months`` closes.

    A generous start window is requested so the resample has enough month-ends;
    only symbols with any history in the window are returned.
    """

    if lookback_months <= 0:
        raise ValueError("lookback_months must be positive")
    # Reach back enough calendar years to cover the requested month count.
    start = date(as_of.year - (lookback_months // 12 + 2), 1, 1)
    bars = repo.get_bars(list(symbols), start, as_of, adjust="adjusted")
    monthly = resample_to_month_end(bars)
    trimmed: dict[str, list[float]] = {}
    for symbol in symbols:
        series = [close for _, close in monthly.get(symbol, [])]
        if series:
            trimmed[symbol] = series[-lookback_months:]
    return trimmed


def _monthly_prices_asof(
    monthly: Mapping[str, list[tuple[date, float]]],
    day: date,
    min_history: int,
) -> dict[str, list[float]]:
    """Closes up to and including ``day``, keeping only symbols with enough history."""

    prices: dict[str, list[float]] = {}
    for symbol, series in monthly.items():
        closes = [close for month_end, close in series if month_end <= day]
        if len(closes) >= min_history:
            prices[symbol] = closes
    return prices


def make_dual_momentum_provider(
    bars: pd.DataFrame,
    *,
    top_n: int = 3,
    budget: float = 1.0,
    cash_symbol: str = "BIL",
    min_history: int = DEFAULT_MIN_HISTORY,
) -> TargetProvider:
    """Wrap C1 dual momentum into a monthly-rebalancing backtest provider.

    Rebalances on the last trading day of each month using month-end closes
    known as of that day. Sessions before enough history (or before the cash
    proxy is priced) hold the current book (return ``None``).
    """

    if min_history <= 0:
        raise ValueError("min_history must be positive")
    monthly = resample_to_month_end(bars)
    rebalance_days = month_end_trading_dates(bars)

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if day not in rebalance_days:
            return None
        prices = _monthly_prices_asof(monthly, day, min_history)
        if cash_symbol not in prices:
            return None
        return dual_momentum_weights(
            prices, day, top_n=top_n, budget=budget, cash_symbol=cash_symbol
        )

    return provider


def make_sector_momentum_provider(
    bars: pd.DataFrame,
    *,
    top_n: int = 3,
    budget: float = 1.0,
    min_history: int = DEFAULT_MIN_HISTORY,
) -> TargetProvider:
    """Wrap S-A sector momentum into a monthly-rebalancing backtest provider."""

    if min_history <= 0:
        raise ValueError("min_history must be positive")
    monthly = resample_to_month_end(bars)
    rebalance_days = month_end_trading_dates(bars)

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if day not in rebalance_days:
            return None
        prices = _monthly_prices_asof(monthly, day, min_history)
        if not any(symbol in GICS_SECTOR_ETFS for symbol in prices):
            return None
        return sector_momentum_weights(prices, day, top_n=top_n, budget=budget)

    return provider


def default_dual_momentum_symbols() -> list[str]:
    """The C1 asset-pool tickers, in declaration order (cash proxy last)."""

    return [sleeve.etf for sleeve in DEFAULT_ASSET_POOL]
