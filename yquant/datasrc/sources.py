"""Factory mapping configured source names to daily-bar adapters."""

from __future__ import annotations

from collections.abc import Callable

from yquant.datasrc.adapters import StooqDailyBarSource, YFinanceDailyBarSource
from yquant.datasrc.protocols import DailyBarSource

_FACTORIES: dict[str, Callable[[], DailyBarSource]] = {
    "yfinance": YFinanceDailyBarSource,
    "stooq": StooqDailyBarSource,
}


def build_daily_bar_source(name: str) -> DailyBarSource:
    """Return a single adapter for ``name`` (case-insensitive)."""

    normalized = name.strip().lower()
    factory = _FACTORIES.get(normalized)
    if factory is None:
        raise ValueError(f"unsupported daily-bar source: {name}")
    return factory()


def build_daily_bar_sources(names: list[str]) -> list[DailyBarSource]:
    """Return de-duplicated adapters preserving first-seen order."""

    sources: list[DailyBarSource] = []
    seen: set[str] = set()
    for name in names:
        normalized = name.strip().lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        sources.append(build_daily_bar_source(name))
    return sources
