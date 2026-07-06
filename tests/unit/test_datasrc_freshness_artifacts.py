from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from yquant.datasrc.artifacts import read_report_artifact, write_report_artifact
from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.freshness import check_daily_bar_freshness, expected_daily_bar_deadline_utc
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


def test_expected_daily_bar_deadline_uses_xnys_market_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_calendar(monkeypatch)

    deadline = expected_daily_bar_deadline_utc(
        date(2024, 1, 3),
        minutes_after_close=45,
        calendar_name="NYSE",
    )

    assert deadline == datetime(2024, 1, 3, 21, 45, tzinfo=UTC)


def test_expected_daily_bar_deadline_rejects_non_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_calendar(monkeypatch)

    with pytest.raises(ValueError, match="is not a NYSE session"):
        expected_daily_bar_deadline_utc(date(2024, 1, 1), calendar_name="NYSE")


def test_expected_daily_bar_deadline_reports_missing_calendar_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing_module(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("yquant.datasrc.freshness.importlib.import_module", _missing_module)

    with pytest.raises(ValueError, match="pandas_market_calendars is required"):
        expected_daily_bar_deadline_utc(date(2024, 1, 3), calendar_name="NYSE")


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


def _patch_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Calendar:
        def schedule(self, start_date: str, end_date: str) -> pd.DataFrame:
            del end_date
            if start_date == "2024-01-01":
                return pd.DataFrame(columns=["market_close"])
            return pd.DataFrame(
                {"market_close": [pd.Timestamp("2024-01-03T21:00:00Z")]}
            )

    fake_module = SimpleNamespace(get_calendar=lambda name: _Calendar())
    monkeypatch.setattr(
        "yquant.datasrc.freshness.importlib.import_module",
        lambda name: fake_module,
    )
