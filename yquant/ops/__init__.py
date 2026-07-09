"""Operations layer (WP11): runbook, layered interval-book, and daily-check.

These are the run-the-thing deliverables the plan calls the 运行手册 / 区间书 /
日检: pure, deterministic, and replay-able so the WP11 exit gate ("四场景演习
台账+委托人独立完成一次日检") is evidence, not prose.
"""

from yquant.ops.daily_check import CheckItem, DailyCheck, build_daily_check
from yquant.ops.interval_book import (
    IntervalBand,
    IntervalBook,
    LayerIntervalBook,
    bands_from_oos,
    build_interval_book,
)
from yquant.ops.runbook import (
    Runbook,
    RunbookSection,
    alert_binding_gaps,
    build_runbook,
)

__all__ = [
    "CheckItem",
    "DailyCheck",
    "IntervalBand",
    "IntervalBook",
    "LayerIntervalBook",
    "Runbook",
    "RunbookSection",
    "alert_binding_gaps",
    "bands_from_oos",
    "build_daily_check",
    "build_interval_book",
    "build_runbook",
]
