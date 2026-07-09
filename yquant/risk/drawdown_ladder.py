"""Drawdown circuit ladder — M8 mechanism ④ (03 §5.8 ④, 08 §5.5).

A portfolio-level, rung-based response to realised drawdown, distinct from the
regime gate (which reacts to the macro state, not to our own equity curve):

  * **>= freeze rung (10%)** — a *freeze-adds* rung: raise a ledger flag and
    leave weights untouched. The M5 discipline layer / proposal builder reads
    this to refuse fresh adds; the engine only records the trip so it is
    auditable and replayable (07).
  * **>= liquidate rung (15%)** — clear the entire Overlay sleeve to cash
    ("Overlay 清至防御") and pin the core vol target to the band floor so the
    downstream vol targeter shrinks the core ("核心层收至波动目标下限").

Like every M8 mechanism this only ever de-risks: it removes the tactical sleeve
and tightens the target, never adds and never levers. The 15% rung is
independent of the regime; when the state machine is also in Crisis the two
simply agree, and both trips land as ledger events.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from yquant.risk.types import RiskEvent, RiskInputs, RiskState
from yquant.strategies.base import TargetPortfolio

FREEZE_RULE = "drawdown_freeze"
LIQUIDATE_RULE = "drawdown_liquidate"
_OVERLAY = "overlay"


def apply_drawdown_ladder(
    desired: TargetPortfolio,
    state: RiskState,
    inputs: RiskInputs,
    as_of: date,
) -> tuple[TargetPortfolio, list[RiskEvent], RiskState]:
    """Apply the drawdown rungs; returns portfolio, events and a tightened state.

    The returned :class:`RiskState` carries a possibly-lowered ``target_vol`` so
    the engine can thread it into the vol targeter (core tightening). A benign
    drawdown returns the inputs unchanged.
    """

    drawdown = inputs.portfolio_drawdown
    if drawdown < state.drawdown_freeze_at:
        return desired, [], state

    if drawdown < state.drawdown_liquidate_at:
        event = RiskEvent(
            as_of=as_of,
            rule=FREEZE_RULE,
            detail={
                "drawdown": round(drawdown, 6),
                "freeze_at": state.drawdown_freeze_at,
                "action": "freeze_adds",
            },
        )
        return desired, [event], state

    # Liquidate rung: clear the Overlay sleeve to cash and pin core vol to floor.
    overlay_symbols = [
        s
        for s, layer in desired.layers.items()
        if layer == _OVERLAY and desired.weights.get(s, 0.0) > 0
    ]
    new_weights = dict(desired.weights)
    freed = 0.0
    for symbol in overlay_symbols:
        freed += new_weights.pop(symbol)
    controlled = TargetPortfolio(
        as_of=desired.as_of,
        weights=new_weights,
        layers={s: layer for s, layer in desired.layers.items() if s in new_weights},
        cash_weight=desired.cash_weight + freed,
    )
    floor = min(state.target_vol_floor, state.target_vol)
    tightened = replace(state, target_vol=floor)
    event = RiskEvent(
        as_of=as_of,
        rule=LIQUIDATE_RULE,
        detail={
            "drawdown": round(drawdown, 6),
            "liquidate_at": state.drawdown_liquidate_at,
            "overlay_cleared": sorted(overlay_symbols),
            "weight_to_cash": round(freed, 6),
            "core_vol_target_floor": round(floor, 6),
        },
    )
    return controlled, [event], tightened
