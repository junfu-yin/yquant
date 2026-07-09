"""Overlay engine (WP16): the 2x-leverage-clause executor and the paper book.

The tactical Overlay sleeve is governed by two deterministic pieces beyond the
committee budgeter (:mod:`yquant.macro.committee`) and the M8 regime gate
(:mod:`yquant.risk.regime_gate`):

* :mod:`yquant.overlay.leverage` — the signed 2x-long leverage clause
  (03 §7 ADR-31): a three-condition open gate, notional-x2 budgeting, hard
  caps, and a 60-day review deadline (T17);
* :mod:`yquant.overlay.paper_book` — the shadow-mode forward-verification
  harness that runs committee opportunities on paper and emits statistics
  (the "纸上机会簿在影子期跑通并出统计" gate, K1').
"""

from yquant.overlay.leverage import (
    LEVERAGE_FACTOR,
    LEVERAGED_2X_SINGLE_CAP,
    LEVERAGED_2X_TOTAL_CAP,
    REVIEW_DEADLINE_DAYS,
    VIX_OPEN_MAX,
    LeverageOpenRequest,
    LeveragePosition,
    LeverageRejection,
    LeverageReviewRow,
    classify_2x,
    open_leverage_position,
    review_leverage_positions,
    three_condition_gate,
)
from yquant.overlay.paper_book import (
    PaperBookStats,
    PaperEntry,
    PaperThesisResult,
    run_paper_book,
)

__all__ = [
    "LEVERAGED_2X_SINGLE_CAP",
    "LEVERAGED_2X_TOTAL_CAP",
    "LEVERAGE_FACTOR",
    "REVIEW_DEADLINE_DAYS",
    "VIX_OPEN_MAX",
    "LeverageOpenRequest",
    "LeveragePosition",
    "LeverageRejection",
    "LeverageReviewRow",
    "PaperBookStats",
    "PaperEntry",
    "PaperThesisResult",
    "classify_2x",
    "open_leverage_position",
    "review_leverage_positions",
    "run_paper_book",
    "three_condition_gate",
]
