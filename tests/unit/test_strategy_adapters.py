"""Unit tests for repo → strategy-series adapters and providers (WP3, 03 §5.3)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.repo import LocalDataRepo
from yquant.strategies.adapters import (
    default_dual_momentum_symbols,
    make_dual_momentum_provider,
    make_sector_momentum_provider,
    month_end_trading_dates,
    monthly_closes_from_repo,
    resample_to_month_end,
)
from yquant.strategies.satellite import SectorMomentumProvider


def _month_end_bars(symbols: tuple[str, ...], months: int, slope: float = 3.0) -> pd.DataFrame:
    """Two bars per month (mid + month-end) so resample must pick the last one."""

    rows = []
    for i in range(months):
        year = 2020 + i // 12
        month = i % 12 + 1
        for tag, day in (("mid", 14), ("end", 27)):
            for j, sym in enumerate(symbols):
                rows.append(
                    {
                        "symbol": sym,
                        "date": date(year, month, day),
                        "close": 100.0 + slope * i + j * 7 + (0.5 if tag == "end" else 0.0),
                        "is_halted": False,
                    }
                )
    return pd.DataFrame(rows)


def test_resample_picks_last_close_of_each_month() -> None:
    bars = _month_end_bars(("SPY",), months=3)
    monthly = resample_to_month_end(bars)
    assert set(monthly) == {"SPY"}
    # Three months, each represented once, ordered oldest→newest by month-end date.
    days = [d for d, _ in monthly["SPY"]]
    assert days == [date(2020, 1, 27), date(2020, 2, 27), date(2020, 3, 27)]
    # The month-end (day 27) close carries the +0.5 tag, not the mid-month bar.
    assert monthly["SPY"][0][1] == pytest.approx(100.5)


def test_month_end_trading_dates_are_last_of_month() -> None:
    bars = _month_end_bars(("SPY",), months=2)
    assert month_end_trading_dates(bars) == {date(2020, 1, 27), date(2020, 2, 27)}


def test_resample_empty_frame_returns_empty() -> None:
    assert resample_to_month_end(pd.DataFrame(columns=["symbol", "date", "close"])) == {}
    assert month_end_trading_dates(pd.DataFrame(columns=["symbol", "date", "close"])) == set()


def test_dual_momentum_provider_rebalances_only_month_end() -> None:
    symbols = default_dual_momentum_symbols()
    bars = _month_end_bars(tuple(symbols), months=16)
    provider = make_dual_momentum_provider(bars, min_history=14)

    closes: dict[str, float] = {}
    # Mid-month day (not a rebalance date) -> hold.
    assert provider(date(2021, 4, 14), closes) is None
    # A month-end after enough history -> a target portfolio.
    target = provider(date(2021, 4, 27), closes)
    assert target is not None
    assert target.invested_weight() + target.cash_weight == pytest.approx(1.0)


def test_dual_momentum_provider_holds_before_enough_history() -> None:
    symbols = default_dual_momentum_symbols()
    bars = _month_end_bars(tuple(symbols), months=16)
    provider = make_dual_momentum_provider(bars, min_history=14)
    # First month-end has only one month of history -> not enough -> hold.
    assert provider(date(2020, 1, 27), {}) is None


def test_sector_momentum_provider_rebalances_month_end() -> None:
    bars = _month_end_bars(("XLK", "XLF", "XLE", "XLV"), months=16)
    provider = make_sector_momentum_provider(bars, min_history=14)
    assert provider(date(2021, 4, 14), {}) is None
    target = provider(date(2021, 4, 27), {})
    assert target is not None
    assert all(layer == "satellite" for layer in target.layers.values())


def _seed_repo(tmp_path: Path, symbols: tuple[str, ...], months: int) -> LocalDataRepo:
    repo = LocalDataRepo(tmp_path)
    rows = []
    for i in range(months):
        year = 2020 + i // 12
        month = i % 12 + 1
        rows.append((date(year, month, 27), 100.0 + 3.0 * i))
    dates = pd.Series([d for d, _ in rows])
    closes = pd.Series([c for _, c in rows])
    for sym in symbols:
        frame = make_daily_bars_frame(
            symbol=sym,
            market="us",
            dates=dates,
            raw_open=closes,
            raw_high=closes,
            raw_low=closes,
            raw_close=closes,
            volume=pd.Series([1_000] * len(rows)),
            source="test",
            asof=datetime(2024, 1, 1, tzinfo=UTC),
        )
        repo.write_daily_bars(frame)
    return repo


def test_monthly_closes_from_repo_trims_to_lookback(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, ("SPY", "BIL"), months=20)
    monthly = monthly_closes_from_repo(repo, ["SPY", "BIL"], date(2021, 8, 27), lookback_months=14)
    assert set(monthly) == {"SPY", "BIL"}
    assert len(monthly["SPY"]) == 14  # trimmed to lookback


def test_sector_provider_predict_uses_repo_resample(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path, ("XLK", "XLF", "XLE", "XLV", "XLI"), months=16)
    provider = SectorMomentumProvider(lookback_months=14, top_n=3)
    as_of = date(2021, 4, 27)
    inferences = provider.predict(as_of, list(repo.get_universe(as_of)), repo)
    assert inferences, "expected sector inferences from repo-driven resample"
    buys = [inf for inf in inferences if inf.output == "buy"]
    assert len(buys) == 3
