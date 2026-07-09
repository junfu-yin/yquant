"""Built-in strategy implementations."""

from __future__ import annotations

from yquant.strategies.adapters import (
    default_dual_momentum_symbols,
    make_dual_momentum_provider,
    make_sector_momentum_provider,
    monthly_closes_from_repo,
    resample_to_month_end,
)

__all__ = [
    "default_dual_momentum_symbols",
    "make_dual_momentum_provider",
    "make_sector_momentum_provider",
    "monthly_closes_from_repo",
    "resample_to_month_end",
]

