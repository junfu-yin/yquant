"""Trend gate — M8 mechanism ② (03 §5.8 / §5.3 C2).

Each asset below its 10-month moving average is not held; the freed weight moves
to cash. Redundant with C1's absolute-momentum filter by design (belt and
braces). Trend status is precomputed into ``RiskInputs.trend_ok``.
"""

from __future__ import annotations

from datetime import date

from yquant.risk.types import RiskEvent, RiskInputs
from yquant.strategies.base import TargetPortfolio

RULE = "trend_gate"


def apply_trend_gate(
    desired: TargetPortfolio,
    inputs: RiskInputs,
    as_of: date,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Zero out weights for symbols below their trend line; move them to cash.

    Symbols missing from ``trend_ok`` are treated as passing (no opinion → no
    forced sale), so an empty inputs map is a no-op.
    """

    gated = {s: w for s, w in desired.weights.items() if inputs.trend_ok.get(s, True) is False}
    if not gated:
        return desired, []

    new_weights = dict(desired.weights)
    freed = 0.0
    for symbol in gated:
        freed += new_weights.pop(symbol)

    controlled = TargetPortfolio(
        as_of=desired.as_of,
        weights=new_weights,
        layers={s: layer for s, layer in desired.layers.items() if s in new_weights},
        cash_weight=desired.cash_weight + freed,
    )
    event = RiskEvent(
        as_of=as_of,
        rule=RULE,
        detail={"gated_symbols": sorted(gated), "weight_to_cash": round(freed, 6)},
    )
    return controlled, [event]
