"""Volatility targeter — M8 mechanism ① (03 §5.8, shared with C3).

When predicted portfolio vol exceeds the target by more than the trigger ratio,
scale down equity-class weights proportionally. Only ever reduces, never adds,
never levers up. Honest caveat (12 §2.1): we ask this only for drawdown control;
its expected-return contribution is logged as "unknown, possibly negative".
"""

from __future__ import annotations

from datetime import date

from yquant.risk.types import RiskEvent, RiskInputs, RiskState
from yquant.strategies.base import TargetPortfolio

RULE = "vol_target"
_EQUITY_CLASS = "equity"


def apply_vol_target(
    desired: TargetPortfolio,
    state: RiskState,
    inputs: RiskInputs,
    as_of: date,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Scale equity weights down if predicted vol breaches target * trigger.

    The freed weight moves to cash (no leverage). Returns the possibly-scaled
    portfolio and any emitted risk events.
    """

    trigger = state.target_vol * state.vol_target_trigger_ratio
    predicted = inputs.predicted_annual_vol
    if predicted <= trigger or predicted <= 0:
        return desired, []

    scale = state.target_vol / predicted  # < 1 by construction
    equity_symbols = [
        s for s in desired.weights if inputs.asset_classes.get(s) == _EQUITY_CLASS
    ]
    if not equity_symbols:
        return desired, []

    new_weights = dict(desired.weights)
    freed = 0.0
    for symbol in equity_symbols:
        old = new_weights[symbol]
        new = old * scale
        freed += old - new
        new_weights[symbol] = new

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
            "predicted_annual_vol": round(predicted, 6),
            "target_vol": state.target_vol,
            "trigger": round(trigger, 6),
            "scale": round(scale, 6),
            "equity_weight_reduced": round(freed, 6),
        },
    )
    return controlled, [event]
