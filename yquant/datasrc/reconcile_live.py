"""Sampled live dual-source reconciliation for M1 daily bars.

Unlike :mod:`yquant.datasrc.reconcile`, which compares rows already persisted in
the repository, this job fetches a sampled set of symbols *live* from two
sources independently (no fallback), then reconciles the two live results and
leaves a quality artifact behind as P3 evidence.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from yquant.datasrc.bars import (
    DAILY_BAR_STORAGE_COLUMNS,
    canonicalize_daily_bars,
    normalize_symbols,
)
from yquant.datasrc.protocols import DailyBarSource, DataRepo
from yquant.datasrc.reconcile import ReconciliationReport, reconcile_daily_bars

FetchStatus = Literal["success", "empty", "failed"]


@dataclass(frozen=True)
class SourceFetchOutcome:
    symbol: str
    source: str
    status: FetchStatus
    row_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class SampledLiveReconciliationReport:
    dataset: str
    start: date
    end: date
    universe_size: int
    sample_size: int
    seed: int | None
    sampled_symbols: tuple[str, ...]
    left_fetches: tuple[SourceFetchOutcome, ...]
    right_fetches: tuple[SourceFetchOutcome, ...]
    reconciliation: ReconciliationReport

    @property
    def left_fetch_failures(self) -> int:
        return sum(1 for outcome in self.left_fetches if outcome.status == "failed")

    @property
    def right_fetch_failures(self) -> int:
        return sum(1 for outcome in self.right_fetches if outcome.status == "failed")

    @property
    def consistency_rate(self) -> float:
        return self.reconciliation.consistency_rate

    @property
    def passed(self) -> bool:
        return (
            self.reconciliation.passed
            and self.left_fetch_failures == 0
            and self.right_fetch_failures == 0
        )


def sample_symbols(
    pool: list[str],
    *,
    sample_size: int | None = None,
    seed: int | None = None,
) -> list[str]:
    """Return a deterministic, sorted sample from ``pool``.

    ``pool`` is normalized (upper-cased, de-duplicated, sorted) before sampling,
    so a given ``seed`` always selects the same symbols regardless of input order.
    """

    normalized = normalize_symbols(pool)
    if sample_size is not None and sample_size < 0:
        raise ValueError("sample_size must be non-negative")
    if sample_size is None or sample_size >= len(normalized):
        return normalized
    rng = random.Random(seed)
    return sorted(rng.sample(normalized, sample_size))


def run_sampled_live_reconciliation(
    left_source: DailyBarSource,
    right_source: DailyBarSource,
    *,
    start: date,
    end: date,
    symbols: list[str] | None = None,
    repo: DataRepo | None = None,
    on_date: date | None = None,
    sample_size: int | None = None,
    seed: int | None = None,
    price_column: str = "close_raw",
    tolerance_bps: float = 10.0,
    minimum_consistency_rate: float = 0.995,
    request_pause_seconds: float = 0.0,
) -> SampledLiveReconciliationReport:
    """Sample symbols, fetch both sources live, and reconcile the results.

    Provide an explicit ``symbols`` pool, or a ``repo`` (its universe on
    ``on_date``, defaulting to ``end``) to sample from. Both sources are always
    queried for every sampled symbol; per-source fetch failures are recorded
    rather than triggering a fallback.
    """

    if end < start:
        raise ValueError("end must be on or after start")
    if left_source.name == right_source.name:
        raise ValueError("left and right sources must differ")
    if request_pause_seconds < 0:
        raise ValueError("request_pause_seconds must be non-negative")

    pool = _resolve_pool(symbols=symbols, repo=repo, on_date=on_date or end)
    universe_size = len(pool)
    sampled = sample_symbols(pool, sample_size=sample_size, seed=seed)

    left_outcomes: list[SourceFetchOutcome] = []
    right_outcomes: list[SourceFetchOutcome] = []
    left_frames: list[pd.DataFrame] = []
    right_frames: list[pd.DataFrame] = []

    for index, symbol in enumerate(sampled):
        if index > 0 and request_pause_seconds > 0:
            time.sleep(request_pause_seconds)
        left_outcome, left_frame = _live_fetch(left_source, symbol, start, end)
        right_outcome, right_frame = _live_fetch(right_source, symbol, start, end)
        left_outcomes.append(left_outcome)
        right_outcomes.append(right_outcome)
        if left_frame is not None:
            left_frames.append(left_frame)
        if right_frame is not None:
            right_frames.append(right_frame)

    left_combined = _combine(left_frames)
    right_combined = _combine(right_frames)
    reconciliation = reconcile_daily_bars(
        left_combined,
        right_combined,
        left_source=left_source.name,
        right_source=right_source.name,
        price_column=price_column,
        tolerance_bps=tolerance_bps,
        minimum_consistency_rate=minimum_consistency_rate,
    )

    return SampledLiveReconciliationReport(
        dataset="daily_bars",
        start=start,
        end=end,
        universe_size=universe_size,
        sample_size=len(sampled),
        seed=seed,
        sampled_symbols=tuple(sampled),
        left_fetches=tuple(left_outcomes),
        right_fetches=tuple(right_outcomes),
        reconciliation=reconciliation,
    )


def _resolve_pool(
    *,
    symbols: list[str] | None,
    repo: DataRepo | None,
    on_date: date,
) -> list[str]:
    if symbols:
        pool = normalize_symbols(symbols)
        if pool:
            return pool
        raise ValueError("symbols must include at least one ticker")
    if repo is not None:
        pool = normalize_symbols(repo.get_universe(on_date, "us"))
        if pool:
            return pool
        raise ValueError("repository universe is empty; provide explicit symbols")
    raise ValueError("provide either symbols or a repo to sample from")


def _live_fetch(
    source: DailyBarSource,
    symbol: str,
    start: date,
    end: date,
) -> tuple[SourceFetchOutcome, pd.DataFrame | None]:
    try:
        frame = source.fetch_daily_bars(symbol, start, end)
    except Exception as exc:
        return (
            SourceFetchOutcome(
                symbol=symbol,
                source=source.name,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )
    if frame is None or frame.empty:
        return SourceFetchOutcome(symbol=symbol, source=source.name, status="empty"), None
    canonical = canonicalize_daily_bars(frame)
    return (
        SourceFetchOutcome(
            symbol=symbol,
            source=source.name,
            status="success",
            row_count=int(len(canonical)),
        ),
        canonical,
    )


def _combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return canonicalize_daily_bars(pd.DataFrame(columns=list(DAILY_BAR_STORAGE_COLUMNS)))
    return canonicalize_daily_bars(pd.concat(frames, ignore_index=True))
