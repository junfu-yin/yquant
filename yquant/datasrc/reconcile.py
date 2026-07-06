"""Cross-source reconciliation for M1 daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from yquant.datasrc.bars import canonicalize_daily_bars


@dataclass(frozen=True)
class ReconciliationMismatch:
    symbol: str
    date: date
    left_value: float
    right_value: float
    diff_bps: float


@dataclass(frozen=True)
class ReconciliationReport:
    dataset: str
    left_source: str
    right_source: str
    tolerance_bps: float
    minimum_consistency_rate: float
    compared_rows: int
    missing_left_rows: int
    missing_right_rows: int
    mismatches: tuple[ReconciliationMismatch, ...]

    @property
    def consistency_rate(self) -> float:
        if self.compared_rows == 0:
            return 0.0
        return (self.compared_rows - len(self.mismatches)) / self.compared_rows

    @property
    def passed(self) -> bool:
        return self.compared_rows > 0 and self.consistency_rate >= self.minimum_consistency_rate


def reconcile_daily_bars(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_source: str,
    right_source: str,
    price_column: str = "close_raw",
    tolerance_bps: float = 10.0,
    minimum_consistency_rate: float = 0.995,
) -> ReconciliationReport:
    """Compare two canonical daily-bar frames on symbol/date close values."""

    if tolerance_bps < 0:
        raise ValueError("tolerance_bps must be non-negative")
    if not 0.0 <= minimum_consistency_rate <= 1.0:
        raise ValueError("minimum_consistency_rate must be in [0, 1]")

    left_bars = canonicalize_daily_bars(left)
    right_bars = canonicalize_daily_bars(right)
    for frame_name, frame in (("left", left_bars), ("right", right_bars)):
        if price_column not in frame.columns:
            raise ValueError(f"{frame_name} daily bars missing price column: {price_column}")

    left_cmp = left_bars.loc[:, ["symbol", "date", price_column]].rename(
        columns={price_column: "left_value"}
    )
    right_cmp = right_bars.loc[:, ["symbol", "date", price_column]].rename(
        columns={price_column: "right_value"}
    )
    merged = left_cmp.merge(right_cmp, on=["symbol", "date"], how="outer", indicator=True)

    missing_left_rows = int((merged["_merge"] == "right_only").sum())
    missing_right_rows = int((merged["_merge"] == "left_only").sum())
    compared = merged.loc[merged["_merge"] == "both"].copy()
    if compared.empty:
        return ReconciliationReport(
            dataset="daily_bars",
            left_source=left_source,
            right_source=right_source,
            tolerance_bps=tolerance_bps,
            minimum_consistency_rate=minimum_consistency_rate,
            compared_rows=0,
            missing_left_rows=missing_left_rows,
            missing_right_rows=missing_right_rows,
            mismatches=(),
        )

    denominator = compared[["left_value", "right_value"]].abs().max(axis=1)
    diff_bps = ((compared["left_value"] - compared["right_value"]).abs() / denominator) * 10_000
    compared["diff_bps"] = diff_bps.fillna(float("inf"))
    mismatch_rows = compared.loc[compared["diff_bps"] > tolerance_bps]

    mismatches = tuple(
        ReconciliationMismatch(
            symbol=str(row.symbol),
            date=row.date,
            left_value=float(row.left_value),
            right_value=float(row.right_value),
            diff_bps=float(row.diff_bps),
        )
        for row in mismatch_rows.itertuples(index=False)
    )
    return ReconciliationReport(
        dataset="daily_bars",
        left_source=left_source,
        right_source=right_source,
        tolerance_bps=tolerance_bps,
        minimum_consistency_rate=minimum_consistency_rate,
        compared_rows=int(len(compared)),
        missing_left_rows=missing_left_rows,
        missing_right_rows=missing_right_rows,
        mismatches=mismatches,
    )
