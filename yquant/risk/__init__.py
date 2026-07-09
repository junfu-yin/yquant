"""M8 risk engine: pre-trade position control (03 §5.8, 12 §5) plus the M9
Layer-1 regime state machine (13 §4).

Public API:
    apply_risk_controls(desired, state, inputs, as_of) -> (controlled, events)
    RiskState, RiskEvent, RiskInputs
    RegimeStateMachine, RegimeState, RegimeConfig, RegimeInputs, RegimeReading
"""

from __future__ import annotations

from yquant.risk.engine import apply_risk_controls
from yquant.risk.state_machine import (
    RegimeConfig,
    RegimeInputs,
    RegimeMemory,
    RegimeReading,
    RegimeState,
    RegimeStateMachine,
    replay,
    step,
)
from yquant.risk.types import RiskEvent, RiskInputs, RiskState

__all__ = [
    "RegimeConfig",
    "RegimeInputs",
    "RegimeMemory",
    "RegimeReading",
    "RegimeState",
    "RegimeStateMachine",
    "RiskEvent",
    "RiskInputs",
    "RiskState",
    "apply_risk_controls",
    "replay",
    "step",
]
