from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.reconcile import reconcile_daily_bars
from yquant.datasrc.repo import LocalDataRepo
from yquant.datasrc.update import DailyBarsUpdater


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


def test_daily_bars_updater_uses_primary_without_touching_backup(tmp_path: Path) -> None:
    primary = FakeDailyBarSource("yfinance", {"AAPL": _bars("AAPL", "yfinance")})
    backup = FakeDailyBarSource("stooq", {"AAPL": _bars("AAPL", "stooq")})
    repo = LocalDataRepo(tmp_path)

    report = DailyBarsUpdater(repo, [primary, backup]).update(
        ["aapl"],
        date(2024, 1, 2),
        date(2024, 1, 3),
    )

    assert report.passed
    assert report.succeeded_symbols == ("AAPL",)
    assert report.failed_symbols == ()
    assert primary.calls == ["AAPL"]
    assert backup.calls == []
    assert len(repo.list_manifests()) == 1
    assert list(repo.get_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))["close"]) == [
        100.0,
        102.0,
    ]


def test_daily_bars_updater_falls_back_after_source_failure(tmp_path: Path) -> None:
    primary = FakeDailyBarSource("yfinance", failing_symbols={"AAPL"})
    backup = FakeDailyBarSource("stooq", {"AAPL": _bars("AAPL", "stooq")})
    repo = LocalDataRepo(tmp_path)

    report = DailyBarsUpdater(repo, [primary, backup]).update(
        ["AAPL"],
        date(2024, 1, 2),
        date(2024, 1, 3),
    )

    assert [attempt.status for attempt in report.attempts] == ["failed", "success"]
    assert report.passed
    assert repo.list_manifests()[0].source == "stooq"


def test_daily_bars_updater_falls_back_after_quality_failure(tmp_path: Path) -> None:
    bad = _bars("AAPL", "yfinance")
    bad.loc[0, "low_raw"] = 999.0
    primary = FakeDailyBarSource("yfinance", {"AAPL": bad})
    backup = FakeDailyBarSource("stooq", {"AAPL": _bars("AAPL", "stooq")})
    repo = LocalDataRepo(tmp_path)

    report = DailyBarsUpdater(repo, [primary, backup]).update(
        ["AAPL"],
        date(2024, 1, 2),
        date(2024, 1, 3),
    )

    assert [attempt.status for attempt in report.attempts] == ["quality_failed", "success"]
    assert report.attempts[0].quality_issues
    assert report.passed


def test_daily_bars_updater_reports_failed_symbols_without_writing(tmp_path: Path) -> None:
    primary = FakeDailyBarSource("yfinance", failing_symbols={"AAPL"})
    backup = FakeDailyBarSource("stooq")
    repo = LocalDataRepo(tmp_path)

    report = DailyBarsUpdater(repo, [primary, backup]).update(
        ["AAPL"],
        date(2024, 1, 2),
        date(2024, 1, 3),
    )

    assert [attempt.status for attempt in report.attempts] == ["failed", "empty"]
    assert report.failed_symbols == ("AAPL",)
    assert not report.passed
    assert repo.list_manifests() == []


def test_reconcile_daily_bars_reports_close_mismatches() -> None:
    left = _bars("AAPL", "yfinance", closes=(100.0, 102.0))
    right = _bars("AAPL", "stooq", closes=(100.05, 105.0))

    report = reconcile_daily_bars(
        left,
        right,
        left_source="yfinance",
        right_source="stooq",
        tolerance_bps=10.0,
        minimum_consistency_rate=0.995,
    )

    assert report.compared_rows == 2
    assert report.missing_left_rows == 0
    assert report.missing_right_rows == 0
    assert len(report.mismatches) == 1
    assert report.mismatches[0].date == date(2024, 1, 3)
    assert report.consistency_rate == 0.5
    assert not report.passed


def test_reconcile_daily_bars_counts_missing_rows() -> None:
    left = _bars("AAPL", "yfinance", closes=(100.0,))
    right = _bars("AAPL", "stooq", closes=(100.0, 102.0))

    report = reconcile_daily_bars(left, right, left_source="yfinance", right_source="stooq")

    assert report.compared_rows == 1
    assert report.missing_left_rows == 1
    assert report.missing_right_rows == 0
    assert report.consistency_rate == 0.5
    assert not report.passed


def test_local_repo_can_filter_canonical_storage_by_source(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(pd.concat([
        _bars("AAPL", "yfinance"),
        _bars("AAPL", "stooq"),
    ]))

    yfinance = repo.get_daily_bars_storage(
        ["AAPL"],
        date(2024, 1, 1),
        date(2024, 1, 31),
        sources=["yfinance"],
    )
    stooq = repo.get_daily_bars_storage(
        ["AAPL"],
        date(2024, 1, 1),
        date(2024, 1, 31),
        sources=["stooq"],
    )

    assert set(yfinance["source"]) == {"yfinance"}
    assert set(stooq["source"]) == {"stooq"}
    assert len(yfinance) == 2
    assert len(stooq) == 2


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
