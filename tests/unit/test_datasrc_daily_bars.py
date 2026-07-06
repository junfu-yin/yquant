from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from yquant.datasrc.adapters import normalize_stooq_daily_bars, normalize_yfinance_daily_bars
from yquant.datasrc.bars import make_daily_bars_frame, repo_view
from yquant.datasrc.manifest import build_manifest, dataframe_content_hash
from yquant.datasrc.quality import check_daily_bars
from yquant.datasrc.repo import LocalDataRepo


def test_yfinance_normalizer_dual_stores_raw_and_adjusted_prices() -> None:
    raw = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "Open": [100.0, 104.0],
            "High": [110.0, 108.0],
            "Low": [99.0, 101.0],
            "Close": [105.0, 102.0],
            "Adj Close": [52.5, 102.0],
            "Volume": [10, 20],
        }
    )

    bars = normalize_yfinance_daily_bars(raw, "aapl")

    assert list(bars["symbol"].unique()) == ["AAPL"]
    assert list(bars["source"].unique()) == ["yfinance"]
    assert bars.loc[0, "close_raw"] == 105.0
    assert bars.loc[0, "close_adjusted"] == 52.5
    assert bars.loc[0, "open_adjusted"] == 50.0
    assert bars.loc[0, "adj_factor"] == 0.5


def test_stooq_normalizer_sorts_ascending_and_marks_unadjusted() -> None:
    raw = pd.DataFrame(
        {
            "Open": [104.0, 100.0],
            "High": [108.0, 110.0],
            "Low": [101.0, 99.0],
            "Close": [102.0, 105.0],
            "Volume": [20, 10],
        },
        index=pd.to_datetime(["2024-01-03", "2024-01-02"]),
    )
    raw.index.name = "Date"

    bars = normalize_stooq_daily_bars(raw, "spy")

    assert list(bars["date"]) == [date(2024, 1, 2), date(2024, 1, 3)]
    assert list(bars["source"].unique()) == ["stooq"]
    assert list(bars["adj_factor"]) == [1.0, 1.0]
    assert list(bars["close_raw"]) == list(bars["close_adjusted"])


def test_quality_detects_duplicate_and_bad_ohlc() -> None:
    bars = _sample_bars()
    duplicate = pd.concat([bars, bars.iloc[[0]]], ignore_index=True)
    duplicate.loc[0, "low_raw"] = 200.0

    report = check_daily_bars(duplicate)

    assert report.has_errors
    assert {issue.rule for issue in report.issues} >= {
        "duplicate_symbol_date_source",
        "ohlc_range_raw",
        "ohlc_bounds_raw",
    }


def test_repo_view_switches_adjusted_and_raw_prices() -> None:
    bars = _sample_bars()

    adjusted = repo_view(bars, "adjusted")
    raw = repo_view(bars, "none")

    assert adjusted.loc[0, "close"] == 99.0
    assert raw.loc[0, "close"] == 100.0


def test_manifest_hash_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    bars = _sample_bars()
    path = tmp_path / "daily_bars.parquet"

    first = build_manifest(bars, dataset="daily_bars", source="yfinance", storage_path=path)
    second = build_manifest(
        bars.sample(frac=1, random_state=1),
        dataset="daily_bars",
        source="yfinance",
        storage_path=path,
    )
    changed = bars.copy()
    changed.loc[0, "close_raw"] = 101.0

    assert first.content_hash == second.content_hash
    assert dataframe_content_hash(changed) != first.content_hash
    assert first.manifest_id.startswith("daily_bars:yfinance:2024-01-02:2024-01-03")


def test_local_data_repo_round_trips_raw_adjusted_and_manifest(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    manifest = repo.write_daily_bars(_sample_bars())

    adjusted = repo.get_bars(["aapl"], date(2024, 1, 1), date(2024, 1, 31))
    raw = repo.get_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31), adjust="none")

    assert manifest.row_count == 2
    assert len(repo.list_manifests()) == 1
    assert list(adjusted["close"]) == pytest.approx([99.0, 101.0])
    assert list(raw["close"]) == [100.0, 102.0]
    assert repo.get_universe(date(2024, 1, 4), market="us") == ["AAPL"]


def test_local_data_repo_upserts_by_symbol_date_source(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path)
    repo.write_daily_bars(_sample_bars())
    replacement = _sample_bars()
    replacement.loc[1, "close_adjusted"] = 101.5
    repo.write_daily_bars(replacement)

    bars = repo.get_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31))

    assert len(bars) == 2
    assert list(bars["close"]) == [99.0, 101.5]
    assert len(repo.list_manifests()) == 2


def _sample_bars() -> pd.DataFrame:
    return make_daily_bars_frame(
        symbol="AAPL",
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"])),
        raw_open=pd.Series([100.0, 101.0]),
        raw_high=pd.Series([101.0, 103.0]),
        raw_low=pd.Series([99.0, 100.0]),
        raw_close=pd.Series([100.0, 102.0]),
        volume=pd.Series([1_000, 1_100]),
        source="yfinance",
        adj_factor=pd.Series([0.99, 0.990196078431]),
        asof=datetime(2024, 1, 4, tzinfo=UTC),
    )
