"""Crowding & liquidity sentinel — M8 mechanism ③ (03 §5.8, 12 §2.3, ADR-26).

Direct engineering response to the 2024 micro-cap incident. For any holding
whose liquidation quantity would exceed ``adv_liquidation_cap`` of its ADV, flag
it and forbid *adding* to it — an add is a target weight above the current one.
Existing size is not force-sold (that is the vol targeter / trend gate's job);
this sentinel only caps new exposure into illiquid names.
"""

from __future__ import annotations

from datetime import date

from yquant.risk.types import RiskEvent, RiskInputs, RiskState
from yquant.strategies.base import TargetPortfolio

RULE = "crowding_liquidity"


def apply_crowding_sentinel(
    desired: TargetPortfolio,
    state: RiskState,
    inputs: RiskInputs,
    as_of: date,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Cap additions to holdings whose liquidation exceeds the ADV cap.

    A target weight is clamped to the symbol's current weight when its position
    value exceeds ``adv * adv_liquidation_cap``. Requires ``portfolio_value > 0``
    to translate weights to values; otherwise it is a no-op.
    """

    if inputs.portfolio_value <= 0:
        return desired, []

    new_weights = dict(desired.weights)
    flagged: list[dict[str, float | str]] = []
    freed = 0.0
    for symbol, target_weight in desired.weights.items():
        adv = inputs.adv.get(symbol)
        if adv is None or adv <= 0:
            continue
        position_value = inputs.position_value.get(symbol, 0.0)
        if position_value <= adv * state.adv_liquidation_cap:
            continue  # Liquid enough — no restriction.

        current_weight = position_value / inputs.portfolio_value
        if target_weight > current_weight:
            freed += target_weight - current_weight
            new_weights[symbol] = current_weight
            flagged.append(
                {
                    "symbol": symbol,
                    "requested_weight": round(target_weight, 6),
                    "capped_weight": round(current_weight, 6),
                    "adv_ratio": round(position_value / adv, 6),
                }
            )

    if not flagged:
        return desired, []

    controlled = TargetPortfolio(
        as_of=desired.as_of,
        weights=new_weights,
        layers=dict(desired.layers),
        cash_weight=desired.cash_weight + freed,
    )
    event = RiskEvent(
        as_of=as_of,
        rule=RULE,
        detail={"adv_liquidation_cap": state.adv_liquidation_cap, "flagged": flagged},
    )
    return controlled, [event]
