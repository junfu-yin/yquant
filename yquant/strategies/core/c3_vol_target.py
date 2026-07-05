"""C3 — volatility target (03 §5.3, weekly).

C3 shares its implementation with M8 mechanism ① (``yquant.risk.vol_target``):
target annualised portfolio vol 10-12%, scale equity-class weights down only,
no leverage. This module is the strategy-side thin wrapper so callers in the
strategy layer do not reach into the risk package directly, and to expose the
vol-forecast helper used to build the risk input.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from yquant.risk.types import RiskEvent, RiskInputs, RiskState
from yquant.risk.vol_target import apply_vol_target
from yquant.strategies.base import TargetPortfolio
from yquant.strategies.indicators import ewma_annualized_vol, portfolio_returns

DEFAULT_TARGET_VOL = 0.11  # midpoint of the 10-12% band


def forecast_portfolio_vol(
    weights: dict[str, float],
    per_symbol_daily_returns: dict[str, Sequence[float]],
    lam: float = 0.94,
) -> float:
    """EWMA-based annualised vol forecast for a weighted portfolio."""

    series = portfolio_returns(weights, per_symbol_daily_returns)
    return ewma_annualized_vol(series, lam=lam)


def apply_vol_target_to_portfolio(
    desired: TargetPortfolio,
    predicted_annual_vol: float,
    asset_classes: dict[str, str],
    as_of: date,
    target_vol: float = DEFAULT_TARGET_VOL,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Apply the C3/M8① vol target using a precomputed vol forecast."""

    state = RiskState(target_vol=target_vol)
    inputs = RiskInputs(
        predicted_annual_vol=predicted_annual_vol,
        asset_classes=asset_classes,
    )
    return apply_vol_target(desired, state, inputs, as_of)
