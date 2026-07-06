from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from yquant.datasrc.macro import (
    MacroUpdater,
    canonicalize_macro_series,
    normalize_yfinance_macro_series,
)
from yquant.datasrc.repo import LocalDataRepo


def _series(series_id: str, values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=len(values), freq="D")
    return pd.DataFrame(
        {"series_id": series_id, "date": dates, "value": values, "source": "test"}
    )


class _FakeMacroSource:
    def __init__(self, name: str, frames: dict[str, pd.DataFrame]) -> None:
        self.name = name
        self.frames = frames
        self.calls: list[str] = []

    def fetch_series(self, series_id: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append(series_id)
        return self.frames.get(series_id, pd.DataFrame())


def test_canonicalize_requires_core_columns() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        canonicalize_macro_series(pd.DataFrame({"series_id": ["X"], "value": [1.0]}))


def test_canonicalize_dedupes_by_series_date_source() -> None:
    frame = pd.concat([_series("^VIX", [13.0, 14.0]), _series("^VIX", [13.5, 14.0])])
    out = canonicalize_macro_series(frame)
    assert len(out) == 2
    assert out.loc[out["date"] == date(2024, 1, 2), "value"].iloc[0] == 13.5  # last wins


def test_normalize_yfinance_macro_uses_close() -> None:
    raw = pd.DataFrame(
        {"Open": [10.0], "Close": [12.5], "Volume": [0]},
        index=pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]), name="Date"),
    )
    out = normalize_yfinance_macro_series(raw, "^GSPC")
    assert out["series_id"].iloc[0] == "^GSPC"
    assert out["value"].iloc[0] == 12.5


def test_macro_updater_persists_and_reports(tmp_path: Path) -> None:
    source = _FakeMacroSource(
        "yfinance",
        {"^GSPC": _series("^GSPC", [4700.0, 4720.0]), "^VIX": _series("^VIX", [13.0, 14.0])},
    )
    repo = LocalDataRepo(tmp_path)

    report = MacroUpdater(repo, source).update(
        ["^gspc", "^vix"], date(2024, 1, 2), date(2024, 1, 3)
    )

    assert report.passed
    assert report.series_ids == ("^GSPC", "^VIX")
    stored = repo.get_macro_series(["^VIX"], date(2024, 1, 1), date(2024, 1, 31))
    assert list(stored["value"]) == [13.0, 14.0]


def test_macro_updater_reports_empty_series_as_failed(tmp_path: Path) -> None:
    source = _FakeMacroSource("yfinance", {"^GSPC": _series("^GSPC", [4700.0])})
    repo = LocalDataRepo(tmp_path)

    report = MacroUpdater(repo, source).update(
        ["^GSPC", "^MISSING"], date(2024, 1, 2), date(2024, 1, 3)
    )

    assert not report.passed
    assert report.failed_series == ("^MISSING",)
    assert [a.status for a in report.attempts] == ["success", "empty"]
