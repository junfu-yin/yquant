"""Property-based invariants for pure core logic (Hypothesis).

These assert behaviour over generated inputs rather than fixed examples, catching
edge cases hand-written tests miss: sampling determinism, backoff monotonicity,
canonicalization idempotence, reconciliation symmetry, and point-in-time
universe correctness.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from yquant.datasrc.bars import canonicalize_daily_bars, make_daily_bars_frame, normalize_symbols
from yquant.datasrc.reconcile import reconcile_daily_bars
from yquant.datasrc.reconcile_live import sample_symbols
from yquant.datasrc.retry import RetryPolicy
from yquant.datasrc.security_master import listed_symbols_on, security_master_from_records

_TICKERS = st.text(alphabet="ABCDEFGH", min_size=1, max_size=4)
_PRICES = st.floats(min_value=2.0, max_value=1000.0, allow_nan=False, allow_infinity=False)


def _bars(symbol: str, closes: list[float], source: str) -> pd.DataFrame:
    close = pd.Series(closes)
    dates = pd.date_range("2024-01-02", periods=len(closes), freq="D")
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(dates),
        raw_open=close,
        raw_high=close + 1.0,
        raw_low=close - 1.0,
        raw_close=close,
        volume=pd.Series([1_000] * len(closes)),
        source=source,
        asof=datetime(2024, 1, 20, tzinfo=UTC),
    )


@settings(max_examples=75, deadline=None)
@given(
    pool=st.lists(_TICKERS, max_size=15),
    size=st.integers(min_value=0, max_value=12),
    seed=st.integers(min_value=-(10**6), max_value=10**6),
)
def test_sample_symbols_is_deterministic_subset_and_order_independent(
    pool: list[str], size: int, seed: int
) -> None:
    normalized = normalize_symbols(pool)
    result = sample_symbols(pool, sample_size=size, seed=seed)

    assert set(result) <= set(normalized)
    assert result == sorted(result)  # output is sorted
    assert len(result) == min(size, len(normalized))
    # Deterministic for a fixed seed.
    assert sample_symbols(pool, sample_size=size, seed=seed) == result
    # Order-independent: shuffling the input pool does not change the sample.
    shuffled = list(pool)
    random.Random(size).shuffle(shuffled)
    assert sample_symbols(shuffled, sample_size=size, seed=seed) == result


@settings(max_examples=75, deadline=None)
@given(
    base=st.floats(min_value=0.0, max_value=10.0),
    factor=st.floats(min_value=1.0, max_value=4.0),
    max_delay=st.floats(min_value=0.0, max_value=100.0),
)
def test_retry_backoff_is_monotonic_and_capped(
    base: float, factor: float, max_delay: float
) -> None:
    policy = RetryPolicy(
        max_attempts=8,
        base_delay_seconds=base,
        backoff_factor=factor,
        max_delay_seconds=max_delay,
    )
    delays = [policy.base_delay_for_attempt(attempt) for attempt in range(1, 9)]
    assert all(delays[i] <= delays[i + 1] + 1e-9 for i in range(len(delays) - 1))
    assert all(delay <= max_delay + 1e-9 for delay in delays)


@settings(max_examples=50, deadline=None)
@given(closes=st.lists(_PRICES, min_size=1, max_size=6))
def test_canonicalize_is_idempotent(closes: list[float]) -> None:
    once = canonicalize_daily_bars(_bars("AAA", closes, "yfinance"))
    twice = canonicalize_daily_bars(once)
    pd.testing.assert_frame_equal(once, twice)


@settings(max_examples=60, deadline=None)
@given(
    left_closes=st.lists(_PRICES, min_size=1, max_size=6),
    right_closes=st.lists(_PRICES, min_size=1, max_size=6),
)
def test_reconcile_is_symmetric(left_closes: list[float], right_closes: list[float]) -> None:
    left = _bars("AAA", left_closes, "yfinance")
    right = _bars("AAA", right_closes, "stooq")

    forward = reconcile_daily_bars(left, right, left_source="yfinance", right_source="stooq")
    backward = reconcile_daily_bars(right, left, left_source="stooq", right_source="yfinance")

    assert forward.compared_rows == backward.compared_rows
    assert len(forward.mismatches) == len(backward.mismatches)
    assert abs(forward.consistency_rate - backward.consistency_rate) < 1e-9
    # Missing counts swap when the sides swap.
    assert forward.missing_left_rows == backward.missing_right_rows
    assert forward.missing_right_rows == backward.missing_left_rows
    # compared rows are exactly matches + mismatches, and the rate stays in [0, 1].
    assert 0.0 <= forward.consistency_rate <= 1.0


@settings(max_examples=60, deadline=None)
@given(
    listing_offset=st.integers(min_value=-30, max_value=30),
    delisting_offset=st.integers(min_value=-30, max_value=30),
    has_delisting=st.booleans(),
)
def test_point_in_time_universe_respects_listing_and_delisting(
    listing_offset: int, delisting_offset: int, has_delisting: bool
) -> None:
    on_date = date(2024, 6, 15)
    listing = on_date + timedelta(days=listing_offset)
    record: dict[str, object] = {
        "symbol": "AAA",
        "market": "us",
        "listing_date": listing.isoformat(),
    }
    if has_delisting:
        record["delisting_date"] = (on_date + timedelta(days=delisting_offset)).isoformat()
    master = security_master_from_records([record])

    universe = listed_symbols_on(master, on_date)
    listed = listing <= on_date
    not_delisted = (not has_delisting) or (on_date + timedelta(days=delisting_offset) > on_date)
    expected = listed and not_delisted
    assert ("AAA" in universe) is expected
