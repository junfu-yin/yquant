"""Batch update orchestration for M1 daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from yquant.datasrc.bars import canonicalize_daily_bars, normalize_symbols
from yquant.datasrc.manifest import DataManifest
from yquant.datasrc.protocols import DailyBarSource
from yquant.datasrc.quality import QualityReport, check_daily_bars
from yquant.datasrc.repo import LocalDataRepo

AttemptStatus = Literal["success", "empty", "failed", "quality_failed"]


@dataclass(frozen=True)
class SourceAttempt:
    symbol: str
    source: str
    status: AttemptStatus
    row_count: int = 0
    error: str | None = None
    quality_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class DailyBarsUpdateReport:
    dataset: str
    symbols: tuple[str, ...]
    start: date
    end: date
    attempts: tuple[SourceAttempt, ...]
    manifests: tuple[DataManifest, ...]
    failed_symbols: tuple[str, ...]

    @property
    def succeeded_symbols(self) -> tuple[str, ...]:
        return tuple(
            attempt.symbol for attempt in self.attempts if attempt.status == "success"
        )

    @property
    def passed(self) -> bool:
        return not self.failed_symbols and bool(self.manifests)


class DailyBarsUpdater:
    """Fetch symbols through ordered sources, validate, and persist to LocalDataRepo."""

    def __init__(self, repo: LocalDataRepo, sources: list[DailyBarSource]) -> None:
        if not sources:
            raise ValueError("at least one daily-bar source is required")
        self.repo = repo
        self.sources = sources

    def update(self, symbols: list[str], start: date, end: date) -> DailyBarsUpdateReport:
        if end < start:
            raise ValueError("end must be on or after start")

        normalized_symbols = tuple(normalize_symbols(symbols))
        attempts: list[SourceAttempt] = []
        failed_symbols: list[str] = []
        accepted_frames: list[pd.DataFrame] = []

        for symbol in normalized_symbols:
            accepted = False
            for source in self.sources:
                attempt, frame = _fetch_and_validate(source, symbol, start, end)
                attempts.append(attempt)
                if attempt.status == "success" and frame is not None:
                    accepted_frames.append(frame)
                    accepted = True
                    break
            if not accepted:
                failed_symbols.append(symbol)

        manifests: tuple[DataManifest, ...] = ()
        if accepted_frames:
            combined = canonicalize_daily_bars(pd.concat(accepted_frames, ignore_index=True))
            manifests = (self.repo.write_daily_bars(combined),)

        return DailyBarsUpdateReport(
            dataset="daily_bars",
            symbols=normalized_symbols,
            start=start,
            end=end,
            attempts=tuple(attempts),
            manifests=manifests,
            failed_symbols=tuple(failed_symbols),
        )


def _fetch_and_validate(
    source: DailyBarSource,
    symbol: str,
    start: date,
    end: date,
) -> tuple[SourceAttempt, pd.DataFrame | None]:
    try:
        frame = source.fetch_daily_bars(symbol, start, end)
    except Exception as exc:
        return (
            SourceAttempt(
                symbol=symbol,
                source=source.name,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )

    if frame.empty:
        return SourceAttempt(symbol=symbol, source=source.name, status="empty"), None

    report = check_daily_bars(frame, expected_symbols=[symbol])
    blocking_issues = _blocking_quality_issues(report)
    if blocking_issues:
        return (
            SourceAttempt(
                symbol=symbol,
                source=source.name,
                status="quality_failed",
                row_count=int(len(frame)),
                quality_issues=blocking_issues,
            ),
            None,
        )

    return (
        SourceAttempt(
            symbol=symbol,
            source=source.name,
            status="success",
            row_count=int(len(frame)),
        ),
        canonicalize_daily_bars(frame),
    )


def _blocking_quality_issues(report: QualityReport) -> tuple[str, ...]:
    issues: list[str] = []
    for issue in report.issues:
        if issue.severity == "error" or issue.rule == "expected_symbols_present":
            issues.append(f"{issue.rule}: {issue.detail}")
    return tuple(issues)
