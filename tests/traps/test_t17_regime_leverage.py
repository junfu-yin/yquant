"""T17 — leverage clause via the M8/M9 regime linkage (06 §2, 13 §7 S2, ADR-32).

The dynamic-gate rejection path (RiskOff/Neutral refuse a fresh 2x request, the
static 2x caps) is exercised in ``test_overlay_dynamic_gate``. This trap covers
the complementary pre-trade path: once the M9 Layer-1 state machine commits a
stressed regime, the engine must shrink the tactical Overlay sleeve — halved in
RiskOff, cleared in Crisis — and it must only ever de-risk (never add, never
lever). A calm regime must leave a within-caps sleeve untouched.
"""

from datetime import date

import pytest

from yquant.risk import RiskInputs, RiskState, apply_risk_controls
from yquant.risk.regime_gate import RULE as GATE_RULE
from yquant.risk.state_machine import RegimeState
from yquant.strategies.base import TargetPortfolio


def _book_with_2x_overlay() -> TargetPortfolio:
    """Core/satellite plus a 2x-long Overlay sleeve inside the v3.1a caps."""

    return TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.70, "XLK": 0.10, "SSO": 0.03, "QLD": 0.02},
        layers={"SPY": "core", "XLK": "satellite", "SSO": "overlay", "QLD": "overlay"},
        cash_weight=0.15,
    )


def _no_scaling_inputs() -> RiskInputs:
    # Vol well within budget so only the regime gate acts (isolates the clause).
    return RiskInputs(predicted_annual_vol=0.05)


def test_t17_crisis_clears_leveraged_overlay_sleeve() -> None:
    portfolio = _book_with_2x_overlay()
    state = RiskState(target_vol=0.11)

    controlled, events = apply_risk_controls(
        portfolio, state, _no_scaling_inputs(), date(2024, 6, 3), regime=RegimeState.CRISIS
    )

    # Whole tactical sleeve gone; core/satellite intact; freed weight to cash.
    assert "SSO" not in controlled.weights
    assert "QLD" not in controlled.weights
    assert controlled.weights["SPY"] == 0.70
    assert controlled.weights["XLK"] == 0.10
    assert controlled.cash_weight == pytest.approx(0.20)
    # Only de-risked: no leverage, invested weight fell.
    assert controlled.invested_weight() < portfolio.invested_weight()
    assert controlled.invested_weight() + controlled.cash_weight == pytest.approx(1.0)
    assert any(e.rule == GATE_RULE for e in events)


def test_t17_risk_off_halves_leveraged_overlay_sleeve() -> None:
    portfolio = _book_with_2x_overlay()
    state = RiskState(target_vol=0.11)

    controlled, events = apply_risk_controls(
        portfolio, state, _no_scaling_inputs(), date(2024, 6, 3), regime=RegimeState.RISK_OFF
    )

    assert controlled.weights["SSO"] == pytest.approx(0.015)
    assert controlled.weights["QLD"] == pytest.approx(0.01)
    assert controlled.weights["SPY"] == 0.70
    assert controlled.cash_weight == pytest.approx(0.175)
    assert controlled.invested_weight() + controlled.cash_weight == pytest.approx(1.0)
    assert any(e.rule == GATE_RULE for e in events)


def test_t17_calm_regime_never_adds_to_the_sleeve() -> None:
    portfolio = _book_with_2x_overlay()
    state = RiskState(target_vol=0.11)

    for regime in (RegimeState.RISK_ON, RegimeState.NEUTRAL):
        controlled, events = apply_risk_controls(
            portfolio, state, _no_scaling_inputs(), date(2024, 6, 3), regime=regime
        )
        # The gate never levers up: a within-caps sleeve is left exactly as-is.
        assert controlled.weights == portfolio.weights
        assert not any(e.rule == GATE_RULE for e in events)
