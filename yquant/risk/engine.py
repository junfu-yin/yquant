"""M8 risk engine orchestrator (03 §5.8, 12 §5).

``apply_risk_controls`` is the single entry point M3/M4 signals pass through
before M5 builds proposals. It applies the four mechanisms in a fixed order and
returns the controlled portfolio plus every ledger event, so the whole run is
replayable (07). All mechanisms only reduce or reallocate to cash — never add,
never lever.

Ordering rationale:
  1. trend gate      — drop broken assets first (most decisive cut).
  2. circuit breaker — regime-level satellite halving.
  3. vol targeter    — scale remaining equity to the vol budget.
  4. crowding        — cap additions into illiquid names last, so it sees the
                       already risk-reduced target weights.
"""

from __future__ import annotations

from datetime import date

from yquant.risk.circuit_breaker import apply_circuit_breaker
from yquant.risk.crowding import apply_crowding_sentinel
from yquant.risk.trend_gate import apply_trend_gate
from yquant.risk.types import RiskEvent, RiskInputs, RiskState
from yquant.risk.vol_target import apply_vol_target
from yquant.strategies.base import TargetPortfolio


def apply_risk_controls(
    desired: TargetPortfolio,
    state: RiskState,
    inputs: RiskInputs,
    as_of: date,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Apply the four M8 pre-trade controls to a desired target portfolio.

    Note: the 03 §5.8 signature is ``(desired, state, repo, as_of)``. We take a
    pre-built :class:`RiskInputs` instead of a live ``DataRepo`` so the engine
    stays pure and unit-testable (T14/T15 use synthetic inputs). See
    :func:`build_risk_inputs` for the repo-backed adapter that produces
    ``RiskInputs`` and is called by the scheduler/backtest layer.
    """

    events: list[RiskEvent] = []
    portfolio = desired

    portfolio, gate_events = apply_trend_gate(portfolio, inputs, as_of)
    events.extend(gate_events)

    portfolio, breaker_events = apply_circuit_breaker(portfolio, state, inputs, as_of)
    events.extend(breaker_events)

    portfolio, vol_events = apply_vol_target(portfolio, state, inputs, as_of)
    events.extend(vol_events)

    portfolio, crowd_events = apply_crowding_sentinel(portfolio, state, inputs, as_of)
    events.extend(crowd_events)

    return portfolio, events
