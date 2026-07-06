from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from yquant.datasrc.artifacts import read_report_artifact, write_report_artifact
from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.freshness import check_daily_bar_freshness
from yquant.datasrc.repo import LocalDataRepo


def test_daily_bar_freshness_reports_fresh_and_late(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_bars("AAPL", asof=datetime(2024, 1, 4, 22, tzinfo=UTC)))

    fresh = check_daily_bar_freshness(
        repo,
        ["AAPL"],
        expected_date=date(2024, 1, 3),
        deadline_utc=datetime(2024, 1, 5, tzinfo=UTC),
    )
    late = check_daily_bar_freshness(
        repo,
        ["AAPL"],
        expected_date=date(2024, 1, 3),
        deadline_utc=datetime(2024, 1, 4, 21, 59, tzinfo=UTC),
    )

    assert fresh.passed
    assert fresh.items[0].status == "fresh"
    assert not late.passed
    assert late.items[0].status == "late"


def test_daily_bar_freshness_reports_stale_and_missing(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_bars("AAPL"))

    report = check_daily_bar_freshness(
        repo,
        ["AAPL", "MSFT"],
        expected_date=date(2024, 1, 4),
        lookback_days=5,
    )

    by_symbol = {item.symbol: item for item in report.items}
    assert not report.passed
    assert by_symbol["AAPL"].status == "stale"
    assert by_symbol["AAPL"].latest_date == date(2024, 1, 3)
    assert by_symbol["MSFT"].status == "missing"
    assert by_symbol["MSFT"].latest_date is None


def test_report_artifact_serializes_report_metadata(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path / "repo")
    repo.write_daily_bars(_bars("AAPL"))
    report = check_daily_bar_freshness(
        repo,
        ["AAPL"],
        expected_date=date(2024, 1, 3),
        generated_at_utc=datetime(2024, 1, 4, tzinfo=UTC),
    )

    artifact = write_report_artifact(
        report,
        tmp_path / "quality",
        kind="daily_bars_freshness",
        generated_at_utc=datetime(2024, 1, 5, 1, 2, 3, tzinfo=UTC),
    )
    payload = read_report_artifact(artifact)

    assert artifact.name == "20240105T010203Z_daily_bars_freshness.json"
    assert payload["kind"] == "daily_bars_freshness"
    assert payload["report"]["dataset"] == "daily_bars"
    assert payload["report"]["passed"] is True
    assert payload["report"]["items"][0]["symbol"] == "AAPL"
    assert payload["report"]["items"][0]["latest_date"] == "2024-01-03"


def _bars(
    symbol: str,
    *,
    asof: datetime = datetime(2024, 1, 4, tzinfo=UTC),
) -> pd.DataFrame:
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"])),
        raw_open=pd.Series([99.0, 101.0]),
        raw_high=pd.Series([101.0, 103.0]),
        raw_low=pd.Series([98.0, 100.0]),
        raw_close=pd.Series([100.0, 102.0]),
        volume=pd.Series([1_000, 1_100]),
        source="yfinance",
        asof=asof,
    )
