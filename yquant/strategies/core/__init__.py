"""Core layer strategies (03 §5.3): C1 dual momentum, C2 trend gate, C3 vol target."""

from __future__ import annotations

from yquant.strategies.core.c1_multiasset_dualmom import (
    DEFAULT_ASSET_POOL,
    AssetSleeve,
    dual_momentum_weights,
)
from yquant.strategies.core.c2_trend_gate import is_above_trend, trend_status
from yquant.strategies.core.c3_vol_target import (
    apply_vol_target_to_portfolio,
    forecast_portfolio_vol,
)

__all__ = [
    "DEFAULT_ASSET_POOL",
    "AssetSleeve",
    "apply_vol_target_to_portfolio",
    "dual_momentum_weights",
    "forecast_portfolio_vol",
    "is_above_trend",
    "trend_status",
]
