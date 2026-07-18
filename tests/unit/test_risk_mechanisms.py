from datetime import date

import pytest

from yquant.risk import RiskInputs, RiskState
from yquant.risk.circuit_breaker import RULE as CB_RULE
from yquant.risk.circuit_breaker import apply_circuit_breaker
from yquant.risk.trend_gate import RULE as GATE_RULE
from yquant.risk.trend_gate import apply_trend_gate
from yquant.strategies.base import TargetPortfolio


def test_risk_inputs_reject_non_finite_value() -> None:
    with pytest.raises(ValueError, match="finite"):
        RiskInputs(predicted_annual_vol=float("nan"))


def test_risk_state_rejects_inverted_drawdown_thresholds() -> None:
    with pytest.raises(ValueError, match="drawdown_freeze_at"):
        RiskState(drawdown_freeze_at=0.20, drawdown_liquidate_at=0.15)


def test_trend_gate_drops_below_trend_asset_to_cash() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.5, "EEM": 0.3},
        layers={"SPY": "core", "EEM": "core"},
        cash_weight=0.2,
    )
    inputs = RiskInputs(predicted_annual_vol=0.1, trend_ok={"SPY": True, "EEM": False})

    controlled, events = apply_trend_gate(portfolio, inputs, date(2024, 6, 3))

    assert "EEM" not in controlled.weights
    assert controlled.weights["SPY"] == 0.5
    assert controlled.cash_weight == pytest.approx(0.5)
    assert events and events[0].rule == GATE_RULE


def test_trend_gate_noop_when_all_pass_or_missing() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.5},
        layers={"SPY": "core"},
        cash_weight=0.5,
    )
    inputs = RiskInputs(predicted_annual_vol=0.1, trend_ok={})

    controlled, events = apply_trend_gate(portfolio, inputs, date(2024, 6, 3))

    assert controlled.weights == portfolio.weights
    assert events == []


def test_circuit_breaker_halves_satellite_after_two_high_vol_weeks() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.5, "XLK": 0.2},
        layers={"SPY": "core", "XLK": "satellite"},
        cash_weight=0.3,
    )
    state = RiskState(target_vol=0.11, circuit_breaker_ratio=1.5)
    # threshold = 0.165; two consecutive weeks above → satellite halved.
    inputs = RiskInputs(predicted_annual_vol=0.1, weekly_realized_vol=[0.12, 0.20, 0.18])

    controlled, events = apply_circuit_breaker(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights["XLK"] == 0.1  # satellite halved
    assert controlled.weights["SPY"] == 0.5  # core untouched
    assert controlled.cash_weight == pytest.approx(0.4)
    assert events and events[0].rule == CB_RULE


def test_circuit_breaker_noop_when_only_one_week_high() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"XLK": 0.2},
        layers={"XLK": "satellite"},
        cash_weight=0.8,
    )
    state = RiskState(target_vol=0.11, circuit_breaker_ratio=1.5)
    inputs = RiskInputs(predicted_annual_vol=0.1, weekly_realized_vol=[0.12, 0.20])
    # Only last week high (0.20 > 0.165, but 0.12 < 0.165) → no trigger.

    controlled, events = apply_circuit_breaker(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights == portfolio.weights
    assert events == []
