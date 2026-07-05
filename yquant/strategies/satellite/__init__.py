"""Satellite layer strategies (03 §5.3): S-A rule, S-B/S-C LLM providers."""

from __future__ import annotations

from yquant.strategies.satellite.llm_providers import (
    EarningsScoreProvider,
    LlmScore,
    NewsDriftProvider,
)
from yquant.strategies.satellite.s_a_sector_momentum import (
    GICS_SECTOR_ETFS,
    SectorMomentumProvider,
    sector_momentum_weights,
)

__all__ = [
    "GICS_SECTOR_ETFS",
    "EarningsScoreProvider",
    "LlmScore",
    "NewsDriftProvider",
    "SectorMomentumProvider",
    "sector_momentum_weights",
]
