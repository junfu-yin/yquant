"""M8 risk engine (03 §5.8, 12 §5): pre-trade position control.

Public API:
    apply_risk_controls(desired, state, inputs, as_of) -> (controlled, events)
    RiskState, RiskEvent, RiskInputs
"""

from __future__ import annotations

from yquant.risk.engine import apply_risk_controls
from yquant.risk.types import RiskEvent, RiskInputs, RiskState

__all__ = ["RiskEvent", "RiskInputs", "RiskState", "apply_risk_controls"]
