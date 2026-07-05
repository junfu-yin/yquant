"""Circuit-breaker ladder — M8 mechanism ④ (03 §5.8, extends 08 §5.5).

New v3 rung: when realized portfolio vol stays above target * circuit_breaker
ratio for two consecutive weeks, halve the entire satellite layer. Freed weight
moves to cash. Trigger executes automatically; release requires a manual ledger
entry (enforced at the discipline/UI layer, not here).
"""

from __future__ import annotations

from datetime import date

from yquant.risk.types import RiskEvent, RiskInputs, RiskState
from yquant.strategies.base import TargetPortfolio

RULE = "circuit_breaker"
_SATELLITE = "satellite"


def apply_circuit_breaker(
    desired: TargetPortfolio,
    state: RiskState,
    inputs: RiskInputs,
    as_of: date,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Halve satellite weights after two consecutive high-vol weeks."""

    weekly = list(inputs.weekly_realized_vol)
    if len(weekly) < 2:
        return desired, []

    threshold = state.target_vol * state.circuit_breaker_ratio
    last_two = weekly[-2:]
    if not all(v > threshold for v in last_two):
        return desired, []

    satellite_symbols = [s for s, layer in desired.layers.items() if layer == _SATELLITE]
    satellite_symbols = [s for s in satellite_symbols if desired.weights.get(s, 0.0) > 0]
    if not satellite_symbols:
        return desired, []

    new_weights = dict(desired.weights)
    freed = 0.0
    for symbol in satellite_symbols:
        old = new_weights[symbol]
        new_weights[symbol] = old / 2.0
        freed += old - new_weights[symbol]

    controlled = TargetPortfolio(
        as_of=desired.as_of,
        weights=new_weights,
        layers=dict(desired.layers),
        cash_weight=desired.cash_weight + freed,
    )
    event = RiskEvent(
        as_of=as_of,
        rule=RULE,
        detail={
            "threshold": round(threshold, 6),
            "last_two_weekly_vol": [round(v, 6) for v in last_two],
            "satellite_halved": sorted(satellite_symbols),
            "weight_to_cash": round(freed, 6),
        },
    )
    return controlled, [event]
