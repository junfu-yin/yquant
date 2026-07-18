from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.reconcile_live import (
    run_sampled_live_reconciliation,
    sample_symbols,
)


class FakeDailyBarSource:
    def __init__(
        self,
        name: str,
        frames: dict[str, pd.DataFrame] | None = None,
        failing_symbols: set[str] | None = None,
    ) -> None:
        self.name = name
        self.frames = frames or {}
        self.failing_symbols = failing_symbols or set()
        self.calls: list[str] = []

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append(symbol)
        if symbol in self.failing_symbols:
            raise RuntimeError(f"{self.name} failed for {symbol}")
        return self.frames.get(symbol, pd.DataFrame())


class FakeRepo:
    def __init__(self, universe: list[str]) -> None:
        self._universe = universe
        self.universe_calls: list[date] = []

    def get_bars(
        self,
        symbols: list[str],
        start: date,
        end: date,
        adjust: str = "adjusted",
    ) -> pd.DataFrame:
        return pd.DataFrame()

    def get_universe(self, on_date: date, market: str = "all") -> list[str]:
        self.universe_calls.append(on_date)
        return list(self._universe)


def test_sample_symbols_is_deterministic_for_a_seed() -> None:
    pool = ["msft", "aapl", "spy", "nvda", "tsla"]

    first = sample_symbols(pool, sample_size=3, seed=7)
    second = sample_symbols(pool, sample_size=3, seed=7)

    assert first == second
    assert len(first) == 3
    assert set(first).issubset({"AAPL", "MSFT", "NVDA", "SPY", "TSLA"})


def test_sample_symbols_returns_full_pool_when_sample_size_exceeds_pool() -> None:
    assert sample_symbols(["aapl", "msft"], sample_size=5, seed=1) == ["AAPL", "MSFT"]


def test_live_reconciliation_fetches_both_sources_and_passes() -> None:
    left = FakeDailyBarSource("yfinance", {"AAPL": _bars("AAPL", "yfinance")})
    right = FakeDailyBarSource("stooq", {"AAPL": _bars("AAPL", "stooq")})

    report = run_sampled_live_reconciliation(
        left,
        right,
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        symbols=["aapl"],
    )

    assert left.calls == ["AAPL"]
    assert right.calls == ["AAPL"]
    assert report.reconciliation.compared_rows == 2
    assert report.left_fetch_failures == 0
    assert report.right_fetch_failures == 0
    assert report.consistency_rate == 1.0
    assert report.passed


def test_live_reconciliation_records_mismatches() -> None:
    left = FakeDailyBarSource(
        "yfinance", {"AAPL": _bars("AAPL", "yfinance", closes=(100.0, 102.0))}
    )
    right = FakeDailyBarSource("stooq", {"AAPL": _bars("AAPL", "stooq", closes=(100.05, 105.0))})

    report = run_sampled_live_reconciliation(
        left,
        right,
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        symbols=["AAPL"],
        tolerance_bps=10.0,
    )

    assert report.reconciliation.compared_rows == 2
    assert len(report.reconciliation.mismatches) == 1
    assert report.consistency_rate == 0.5
    assert not report.passed


def test_live_reconciliation_records_per_source_fetch_failures() -> None:
    left = FakeDailyBarSource(
        "yfinance", {"AAPL": _bars("AAPL", "yfinance")}, failing_symbols={"MSFT"}
    )
    right = FakeDailyBarSource(
        "stooq",
        {"AAPL": _bars("AAPL", "stooq"), "MSFT": _bars("MSFT", "stooq")},
    )

    report = run_sampled_live_reconciliation(
        left,
        right,
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        symbols=["AAPL", "MSFT"],
    )

    assert report.left_fetch_failures == 1
    assert report.right_fetch_failures == 0
    # AAPL is present on both sides and matches, while MSFT is missing on the
    # failed side. Missing rows count against reconciliation consistency.
    assert not report.reconciliation.passed
    assert not report.passed


def test_live_reconciliation_samples_from_repo_universe() -> None:
    repo = FakeRepo(["AAPL", "MSFT", "SPY", "NVDA"])
    left = FakeDailyBarSource("yfinance")
    right = FakeDailyBarSource("stooq")

    report = run_sampled_live_reconciliation(
        left,
        right,
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        repo=repo,
        sample_size=2,
        seed=11,
    )

    assert repo.universe_calls == [date(2024, 1, 3)]
    assert report.universe_size == 4
    assert report.sample_size == 2
    assert len(report.sampled_symbols) == 2
    assert left.calls == list(report.sampled_symbols)
    assert right.calls == list(report.sampled_symbols)


def test_live_reconciliation_rejects_identical_sources() -> None:
    source = FakeDailyBarSource("yfinance")

    with pytest.raises(ValueError, match="must differ"):
        run_sampled_live_reconciliation(
            source,
            source,
            start=date(2024, 1, 2),
            end=date(2024, 1, 3),
            symbols=["AAPL"],
        )


def test_live_reconciliation_requires_a_pool_source() -> None:
    left = FakeDailyBarSource("yfinance")
    right = FakeDailyBarSource("stooq")

    with pytest.raises(ValueError, match="symbols or a repo"):
        run_sampled_live_reconciliation(
            left,
            right,
            start=date(2024, 1, 2),
            end=date(2024, 1, 3),
        )


def _bars(
    symbol: str,
    source: str,
    closes: tuple[float, ...] = (100.0, 102.0),
) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=len(closes), freq="D")
    close_series = pd.Series(closes)
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(dates),
        raw_open=close_series - 0.5,
        raw_high=close_series + 1.0,
        raw_low=close_series - 1.0,
        raw_close=close_series,
        volume=pd.Series([1_000 + index for index in range(len(closes))]),
        source=source,
        asof=datetime(2024, 1, 4, tzinfo=UTC),
    )
