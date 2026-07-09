from datetime import date

import pytest

from yquant.risk import RiskInputs, RiskState, apply_risk_controls
from yquant.risk.regime_gate import RULE as GATE_RULE
from yquant.risk.regime_gate import apply_regime_gate, effective_target_vol
from yquant.risk.state_machine import RegimeState
from yquant.strategies.base import TargetPortfolio


def _overlay_portfolio() -> TargetPortfolio:
    """A book with core + satellite + a tactical Overlay sleeve."""

    return TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.6, "XLK": 0.15, "SSO": 0.05, "QQQ": 0.05},
        layers={"SPY": "core", "XLK": "satellite", "SSO": "overlay", "QQQ": "overlay"},
        cash_weight=0.15,
    )


def test_regime_gate_halves_overlay_in_risk_off() -> None:
    portfolio = _overlay_portfolio()

    controlled, events = apply_regime_gate(portfolio, RegimeState.RISK_OFF, date(2024, 6, 3))

    # Overlay sleeves halved; core / satellite untouched.
    assert controlled.weights["SSO"] == pytest.approx(0.025)
    assert controlled.weights["QQQ"] == pytest.approx(0.025)
    assert controlled.weights["SPY"] == 0.6
    assert controlled.weights["XLK"] == 0.15
    # Freed 0.05 of overlay went to cash; no leverage.
    assert controlled.cash_weight == pytest.approx(0.20)
    assert controlled.invested_weight() + controlled.cash_weight == pytest.approx(1.0)
    assert events and events[0].rule == GATE_RULE
    assert events[0].detail["retention"] == 0.5
    assert events[0].detail["overlay_symbols"] == ["QQQ", "SSO"]
    assert events[0].detail["weight_to_cash"] == pytest.approx(0.05)


def test_regime_gate_clears_overlay_in_crisis() -> None:
    portfolio = _overlay_portfolio()

    controlled, events = apply_regime_gate(portfolio, RegimeState.CRISIS, date(2024, 6, 3))

    # Overlay sleeves removed entirely; core / satellite untouched.
    assert "SSO" not in controlled.weights
    assert "QQQ" not in controlled.weights
    assert "SSO" not in controlled.layers
    assert "QQQ" not in controlled.layers
    assert controlled.weights["SPY"] == 0.6
    assert controlled.weights["XLK"] == 0.15
    assert controlled.cash_weight == pytest.approx(0.25)
    assert controlled.invested_weight() + controlled.cash_weight == pytest.approx(1.0)
    assert events and events[0].detail["retention"] == 0.0
    assert events[0].detail["weight_to_cash"] == pytest.approx(0.10)


def test_regime_gate_noop_when_risk_on_or_neutral() -> None:
    portfolio = _overlay_portfolio()

    for state in (RegimeState.RISK_ON, RegimeState.NEUTRAL):
        controlled, events = apply_regime_gate(portfolio, state, date(2024, 6, 3))
        assert controlled.weights == portfolio.weights
        assert controlled.cash_weight == portfolio.cash_weight
        assert events == []


def test_regime_gate_noop_when_no_overlay_layer() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.6, "XLK": 0.2},
        layers={"SPY": "core", "XLK": "satellite"},
        cash_weight=0.2,
    )

    controlled, events = apply_regime_gate(portfolio, RegimeState.CRISIS, date(2024, 6, 3))

    assert controlled.weights == portfolio.weights
    assert events == []


def test_regime_gate_noop_when_overlay_weight_zero() -> None:
    # An overlay symbol tagged but at zero weight is not a live position.
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.6},
        layers={"SPY": "core", "SSO": "overlay"},
        cash_weight=0.4,
    )

    controlled, events = apply_regime_gate(portfolio, RegimeState.RISK_OFF, date(2024, 6, 3))

    assert controlled.weights == portfolio.weights
    assert events == []


def test_effective_target_vol_by_regime() -> None:
    state = RiskState(target_vol=0.12, target_vol_floor=0.10)

    # Calm regimes keep the nominal target; None too.
    assert effective_target_vol(state, None) == 0.12
    assert effective_target_vol(state, RegimeState.RISK_ON) == 0.12
    assert effective_target_vol(state, RegimeState.NEUTRAL) == 0.12
    # RiskOff moves to the midpoint of the target/floor band.
    assert effective_target_vol(state, RegimeState.RISK_OFF) == pytest.approx(0.11)
    # Crisis pins to the floor.
    assert effective_target_vol(state, RegimeState.CRISIS) == pytest.approx(0.10)


def test_effective_target_vol_never_loosens_when_floor_above_target() -> None:
    # Defensive: a mis-set floor above target must not raise the effective target.
    state = RiskState(target_vol=0.09, target_vol_floor=0.15)

    assert effective_target_vol(state, RegimeState.CRISIS) == pytest.approx(0.09)
    assert effective_target_vol(state, RegimeState.RISK_OFF) == pytest.approx(0.09)


def test_engine_regime_none_is_backward_compatible() -> None:
    portfolio = _overlay_portfolio()
    state = RiskState(target_vol=0.11)
    inputs = RiskInputs(predicted_annual_vol=0.10)

    without = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))
    with_none = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3), regime=None)

    assert without[0].weights == with_none[0].weights
    assert without[1] == with_none[1] == []


def test_engine_applies_regime_gate_then_tightens_vol_target() -> None:
    portfolio = _overlay_portfolio()
    state = RiskState(target_vol=0.12, target_vol_floor=0.10)
    # Predicted vol 0.13 is within the nominal trigger (0.12 * 1.15 = 0.138) so it
    # would not scale on its own — but above the Crisis-tightened trigger
    # (0.10 * 1.15 = 0.115), so the tightened target is what makes the vol
    # targeter bite. This proves the engine uses the tightened effective_state.
    inputs = RiskInputs(
        predicted_annual_vol=0.13,
        asset_classes={"SPY": "equity", "XLK": "equity", "SSO": "equity", "QQQ": "equity"},
    )

    controlled, events = apply_risk_controls(
        portfolio, state, inputs, date(2024, 6, 3), regime=RegimeState.CRISIS
    )

    rules = [e.rule for e in events]
    # Overlay cleared by the regime gate, then equity scaled to the 0.10 floor.
    assert GATE_RULE in rules
    assert "vol_target" in rules
    assert "SSO" not in controlled.weights
    assert "QQQ" not in controlled.weights
    # Vol targeter scaled surviving equity by 0.10 / 0.13.
    assert controlled.weights["SPY"] == pytest.approx(0.6 * 0.10 / 0.13)
    assert controlled.invested_weight() + controlled.cash_weight == pytest.approx(1.0)


def test_engine_risk_on_leaves_overlay_and_vol_target_untouched() -> None:
    portfolio = _overlay_portfolio()
    state = RiskState(target_vol=0.12, target_vol_floor=0.10)
    inputs = RiskInputs(predicted_annual_vol=0.11)

    controlled, events = apply_risk_controls(
        portfolio, state, inputs, date(2024, 6, 3), regime=RegimeState.RISK_ON
    )

    assert controlled.weights == portfolio.weights
    assert events == []
