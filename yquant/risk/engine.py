"""M8 risk engine orchestrator (03 §5.8, 12 §5).

``apply_risk_controls`` is the single entry point M3/M4 signals pass through
before M5 builds proposals. It applies the four mechanisms in a fixed order and
returns the controlled portfolio plus every ledger event, so the whole run is
replayable (07). All mechanisms only reduce or reallocate to cash — never add,
never lever.

Ordering rationale:
  0. regime gate     — the M9 state machine's veto (ADR-32): shrink the Overlay
                       layer first (RiskOff halves it, Crisis clears it) and
                       tighten the core vol target, so every downstream
                       mechanism sees the de-risked, de-levered book.
  1. trend gate      — drop broken assets first (most decisive cut).
  2. circuit breaker — regime-level satellite halving.
  3. vol targeter    — scale remaining equity to the (possibly tightened) budget.
  4. crowding        — cap additions into illiquid names last, so it sees the
                       already risk-reduced target weights.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from yquant.risk.circuit_breaker import apply_circuit_breaker
from yquant.risk.crowding import apply_crowding_sentinel
from yquant.risk.regime_gate import apply_regime_gate, effective_target_vol
from yquant.risk.state_machine import RegimeState
from yquant.risk.trend_gate import apply_trend_gate
from yquant.risk.types import RiskEvent, RiskInputs, RiskState
from yquant.risk.vol_target import apply_vol_target
from yquant.strategies.base import TargetPortfolio


def apply_risk_controls(
    desired: TargetPortfolio,
    state: RiskState,
    inputs: RiskInputs,
    as_of: date,
    regime: RegimeState | None = None,
) -> tuple[TargetPortfolio, list[RiskEvent]]:
    """Apply the M8 pre-trade controls to a desired target portfolio.

    Note: the 03 §5.8 signature is ``(desired, state, repo, as_of)``. We take a
    pre-built :class:`RiskInputs` instead of a live ``DataRepo`` so the engine
    stays pure and unit-testable (T14/T15 use synthetic inputs). See
    :func:`build_risk_inputs` for the repo-backed adapter that produces
    ``RiskInputs`` and is called by the scheduler/backtest layer.

    When ``regime`` is supplied, the M9 state machine's veto is applied first
    (Overlay shrink + core vol-target tightening, 03 §5.9 / ADR-32). Passing
    ``None`` leaves behaviour identical to the four-mechanism engine.
    """

    events: list[RiskEvent] = []
    portfolio = desired
    effective_state = state

    if regime is not None:
        portfolio, gate_events = apply_regime_gate(portfolio, regime, as_of)
        events.extend(gate_events)
        effective_state = replace(state, target_vol=effective_target_vol(state, regime))

    portfolio, gate_events = apply_trend_gate(portfolio, inputs, as_of)
    events.extend(gate_events)

    portfolio, breaker_events = apply_circuit_breaker(portfolio, effective_state, inputs, as_of)
    events.extend(breaker_events)

    portfolio, vol_events = apply_vol_target(portfolio, effective_state, inputs, as_of)
    events.extend(vol_events)

    portfolio, crowd_events = apply_crowding_sentinel(portfolio, effective_state, inputs, as_of)
    events.extend(crowd_events)

    return portfolio, events
