from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from random import Random

import pandas as pd
import pytest

from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.repo import LocalDataRepo
from yquant.datasrc.retry import RetryPolicy, run_with_retry
from yquant.datasrc.update import DailyBarsUpdater


def test_retry_policy_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="backoff_factor"):
        RetryPolicy(backoff_factor=0.5)


def test_base_delay_grows_and_is_capped() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, backoff_factor=2.0, max_delay_seconds=5.0)
    assert policy.base_delay_for_attempt(1) == 1.0
    assert policy.base_delay_for_attempt(2) == 2.0
    assert policy.base_delay_for_attempt(3) == 4.0
    assert policy.base_delay_for_attempt(4) == 5.0  # capped


def test_run_with_retry_succeeds_after_transient_failures() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    result = run_with_retry(
        flaky,
        RetryPolicy(max_attempts=3, base_delay_seconds=1.0, backoff_factor=2.0),
        sleep=slept.append,
    )

    assert result == "ok"
    assert calls["n"] == 3
    assert slept == [1.0, 2.0]


def test_run_with_retry_reraises_after_exhausting_attempts() -> None:
    slept: list[float] = []

    def always_fails() -> str:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        run_with_retry(
            always_fails,
            RetryPolicy(max_attempts=2, base_delay_seconds=0.5),
            sleep=slept.append,
        )

    assert len(slept) == 1  # one backoff between the two attempts


def test_run_with_retry_applies_bounded_jitter() -> None:
    slept: list[float] = []

    def always_fails() -> str:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        run_with_retry(
            always_fails,
            RetryPolicy(max_attempts=2, base_delay_seconds=1.0, jitter_seconds=0.5),
            sleep=slept.append,
            rng=Random(0),
        )

    assert 1.0 <= slept[0] <= 1.5


def test_run_with_retry_only_catches_declared_errors() -> None:
    def fails() -> str:
        raise KeyError("k")

    with pytest.raises(KeyError):
        run_with_retry(
            fails,
            RetryPolicy(max_attempts=3),
            retry_on=(ValueError,),
            sleep=lambda _: None,
        )


class _FlakyThenGoodSource:
    def __init__(self, name: str, frame: pd.DataFrame, fail_times: int) -> None:
        self.name = name
        self.frame = frame
        self.fail_times = fail_times
        self.calls = 0

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient")
        return self.frame


def test_updater_retries_flaky_source_and_succeeds(tmp_path: Path) -> None:
    frame = make_daily_bars_frame(
        symbol="AAPL",
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"])),
        raw_open=pd.Series([99.0, 101.0]),
        raw_high=pd.Series([101.0, 103.0]),
        raw_low=pd.Series([98.0, 100.0]),
        raw_close=pd.Series([100.0, 102.0]),
        volume=pd.Series([1_000, 1_100]),
        source="yfinance",
        asof=datetime(2024, 1, 4, tzinfo=UTC),
    )
    source = _FlakyThenGoodSource("yfinance", frame, fail_times=2)
    repo = LocalDataRepo(tmp_path)

    report = DailyBarsUpdater(
        repo,
        [source],
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0),
        sleep=lambda _: None,
    ).update(["AAPL"], date(2024, 1, 2), date(2024, 1, 3))

    assert report.passed
    assert source.calls == 3
    assert report.succeeded_symbols == ("AAPL",)
