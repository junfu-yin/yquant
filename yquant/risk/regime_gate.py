"""Regime gate — M8 mechanism ⑤ (03 §5.8 ④ / §5.9, 13 §4 / §7 S2, ADR-32).

The M9 Layer-1 state machine holds veto power over the tactical Overlay layer.
This mechanism translates the committed :class:`RegimeState` into two pre-trade
actions M5 sees before building proposals:

  * **RiskOff** — halve every Overlay-layer weight (2x-long sleeves included);
    freed weight to cash. Realises S2's "Overlay longs halved, 2x cleared".
  * **Crisis** — clear the entire Overlay layer to cash ("defensive only"; a
    long-only book expresses defence by *not holding* the tactical sleeve).

Core and satellite layers are untouched here — the vol targeter tightens the
core separately via :func:`effective_target_vol`. Like every M8 mechanism this
only reduces or reallocates to cash: never adds, never levers.

RiskOn / Neutral are no-ops: the gate never *adds* leverage, it only removes it.
"""

from __future__ import annotations

from datetime import date

from yquant.risk.state_machine import RegimeState
from yquant.risk.types import RiskEvent, RiskState
from yquant.strategies.base import TargetPortfolio

RULE = "regime_gate"
_OVERLAY = "overlay"

# Fraction of each Overlay weight retained per state (1.0 = untouched).
_RETENTION: dict[RegimeState, float] = {
    RegimeState.RISK_ON: 1.0,
    RegimeState.NEUTRAL: 1.0,
    RegimeState.RISK_OFF: 0.5,
    RegimeState.CRISIS: 0.0,
}


def apply_regime_gate(
    desired: TargetPortfolio,
    regime: RegimeState,
    as_of: date,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Shrink the Overlay layer according to the committed regime state."""

    retention = _RETENTION[regime]
    if retention >= 1.0:
        return desired, []

    overlay_symbols = [
        s for s, layer in desired.layers.items()
        if layer == _OVERLAY and desired.weights.get(s, 0.0) > 0
    ]
    if not overlay_symbols:
        return desired, []

    new_weights = dict(desired.weights)
    freed = 0.0
    for symbol in overlay_symbols:
        old = new_weights[symbol]
        new = old * retention
        freed += old - new
        if new > 0:
            new_weights[symbol] = new
        else:
            new_weights.pop(symbol)

    controlled = TargetPortfolio(
        as_of=desired.as_of,
        weights=new_weights,
        layers={s: layer for s, layer in desired.layers.items() if s in new_weights},
        cash_weight=desired.cash_weight + freed,
    )
    event = RiskEvent(
        as_of=as_of,
        rule=RULE,
        detail={
            "regime": regime.value,
            "retention": retention,
            "overlay_symbols": sorted(overlay_symbols),
            "weight_to_cash": round(freed, 6),
        },
    )
    return controlled, [event]


def effective_target_vol(state: RiskState, regime: RegimeState | None) -> float:
    """Tighten the core vol target under stress (03 §5.8 ④ / §5.9, 13 §7 S2).

    RiskOn / Neutral / no-regime keep the nominal target; RiskOff moves to the
    midpoint of the target/floor band; Crisis pins it to the band floor. The
    result is only ever <= ``state.target_vol`` — the gate tightens, never loosens.
    """

    if regime is None or regime in (RegimeState.RISK_ON, RegimeState.NEUTRAL):
        return state.target_vol
    floor = min(state.target_vol_floor, state.target_vol)
    if regime is RegimeState.CRISIS:
        return floor
    return (state.target_vol + floor) / 2.0  # RiskOff: halfway to the floor
