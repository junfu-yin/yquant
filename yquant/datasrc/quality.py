"""Data-quality checks for canonical M1 daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

import pandas as pd

from yquant.datasrc.bars import (
    ADJUSTED_PRICE_COLUMNS,
    DAILY_BAR_STORAGE_COLUMNS,
    RAW_PRICE_COLUMNS,
    canonicalize_daily_bars,
    normalize_symbols,
)

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class QualityIssue:
    severity: Severity
    rule: str
    detail: str
    symbol: str | None = None
    date: date | None = None


@dataclass(frozen=True)
class QualityReport:
    dataset: str
    row_count: int
    issues: tuple[QualityIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    def raise_for_errors(self) -> None:
        if not self.has_errors:
            return
        details = "; ".join(
            f"{issue.rule}: {issue.detail}" for issue in self.issues if issue.severity == "error"
        )
        raise ValueError(f"daily-bar quality check failed: {details}")


def check_daily_bars(
    frame: pd.DataFrame,
    *,
    expected_symbols: list[str] | None = None,
) -> QualityReport:
    """Validate canonical daily bars before they become repository truth."""

    issues: list[QualityIssue] = []
    missing = [column for column in DAILY_BAR_STORAGE_COLUMNS if column not in frame.columns]
    if missing:
        issues.append(
            QualityIssue(
                severity="error",
                rule="required_columns",
                detail=f"missing columns: {missing}",
            )
        )
        return QualityReport("daily_bars", int(len(frame)), tuple(issues))

    bars = canonicalize_daily_bars(frame)
    if bars.empty:
        issues.append(QualityIssue("error", "non_empty", "daily bars frame is empty"))
        return QualityReport("daily_bars", 0, tuple(issues))

    issues.extend(_missing_value_issues(bars))
    issues.extend(_duplicate_issues(bars))
    issues.extend(_price_issues(bars))
    issues.extend(_volume_issues(bars))
    issues.extend(_expected_symbol_issues(bars, expected_symbols))
    return QualityReport("daily_bars", int(len(bars)), tuple(issues))


def _missing_value_issues(frame: pd.DataFrame) -> list[QualityIssue]:
    required = [
        "symbol",
        "market",
        "date",
        "source",
        "asof",
        "volume",
        "adj_factor",
        *RAW_PRICE_COLUMNS,
        *ADJUSTED_PRICE_COLUMNS,
    ]
    issues: list[QualityIssue] = []
    for column in required:
        null_count = int(frame[column].isna().sum())
        if null_count:
            issues.append(
                QualityIssue(
                    severity="error",
                    rule="missing_values",
                    detail=f"{column} has {null_count} missing values",
                )
            )
    return issues


def _duplicate_issues(frame: pd.DataFrame) -> list[QualityIssue]:
    duplicates = frame.duplicated(["symbol", "date", "source"], keep=False)
    count = int(duplicates.sum())
    if count == 0:
        return []
    return [
        QualityIssue(
            severity="error",
            rule="duplicate_symbol_date_source",
            detail=f"{count} rows share the same symbol/date/source key",
        )
    ]


def _price_issues(frame: pd.DataFrame) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for prefix in ("raw", "adjusted"):
        low = frame[f"low_{prefix}"]
        high = frame[f"high_{prefix}"]
        open_ = frame[f"open_{prefix}"]
        close = frame[f"close_{prefix}"]

        non_positive = (low <= 0) | (high <= 0) | (open_ <= 0) | (close <= 0)
        if int(non_positive.sum()):
            issues.append(
                QualityIssue(
                    severity="error",
                    rule=f"positive_{prefix}_prices",
                    detail=f"{int(non_positive.sum())} rows have non-positive prices",
                )
            )

        bad_range = low > high
        if int(bad_range.sum()):
            issues.append(
                QualityIssue(
                    severity="error",
                    rule=f"ohlc_range_{prefix}",
                    detail=f"{int(bad_range.sum())} rows have low greater than high",
                )
            )

        outside = (open_ < low) | (open_ > high) | (close < low) | (close > high)
        if int(outside.sum()):
            issues.append(
                QualityIssue(
                    severity="error",
                    rule=f"ohlc_bounds_{prefix}",
                    detail=f"{int(outside.sum())} rows have open/close outside low/high",
                )
            )

    bad_factor = frame["adj_factor"] <= 0
    if int(bad_factor.sum()):
        issues.append(
            QualityIssue(
                severity="error",
                rule="positive_adj_factor",
                detail=f"{int(bad_factor.sum())} rows have non-positive adjustment factors",
            )
        )
    return issues


def _volume_issues(frame: pd.DataFrame) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    negative_volume = frame["volume"] < 0
    if int(negative_volume.sum()):
        issues.append(
            QualityIssue(
                severity="error",
                rule="non_negative_volume",
                detail=f"{int(negative_volume.sum())} rows have negative volume",
            )
        )
    if "amount" in frame.columns:
        negative_amount = frame["amount"] < 0
        if int(negative_amount.sum()):
            issues.append(
                QualityIssue(
                    severity="error",
                    rule="non_negative_amount",
                    detail=f"{int(negative_amount.sum())} rows have negative amount",
                )
            )
    return issues


def _expected_symbol_issues(
    frame: pd.DataFrame,
    expected_symbols: list[str] | None,
) -> list[QualityIssue]:
    if expected_symbols is None:
        return []
    expected = set(normalize_symbols(expected_symbols))
    actual = set(cast(list[str], frame["symbol"].dropna().astype(str).unique().tolist()))
    missing = sorted(expected - actual)
    if not missing:
        return []
    return [
        QualityIssue(
            severity="warning",
            rule="expected_symbols_present",
            detail=f"missing expected symbols: {missing}",
        )
    ]
