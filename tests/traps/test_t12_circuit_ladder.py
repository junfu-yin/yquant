"""T12 — drawdown circuit ladder (06 §2, 03 §5.8 ④).

Two rungs on our own equity curve, independent of the macro regime:

  * at the 10% freeze rung the engine only *flags* (M5 refuses fresh adds) —
    weights are untouched and no risk is added;
  * at the 15% liquidate rung the whole Overlay sleeve is cleared to cash and
    the core vol target is pinned to the band floor, so the vol targeter then
    shrinks the core.

Below the freeze line the ladder is a no-op. Every trip lands as a ledger event.
"""

from datetime import date

import pytest

from yquant.risk import RiskInputs, RiskState, apply_risk_controls
from yquant.risk.drawdown_ladder import FREEZE_RULE, LIQUIDATE_RULE
from yquant.risk.vol_target import RULE as VOL_RULE
from yquant.strategies.base import TargetPortfolio


def _book_with_overlay() -> TargetPortfolio:
    return TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.60, "XLK": 0.10, "SSO": 0.04},
        layers={"SPY": "core", "XLK": "satellite", "SSO": "overlay"},
        cash_weight=0.26,
    )


def test_t12_below_freeze_line_is_a_noop() -> None:
    portfolio = _book_with_overlay()
    state = RiskState(target_vol=0.11)
    inputs = RiskInputs(predicted_annual_vol=0.05, portfolio_drawdown=0.08)

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights == portfolio.weights
    assert not [e for e in events if e.rule in {FREEZE_RULE, LIQUIDATE_RULE}]


def test_t12_freeze_rung_flags_without_touching_weights() -> None:
    portfolio = _book_with_overlay()
    state = RiskState(target_vol=0.11)
    # 12% drawdown: past the 10% freeze line, below the 15% liquidate line.
    inputs = RiskInputs(predicted_annual_vol=0.05, portfolio_drawdown=0.12)

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    # Freeze only flags; it must never de-risk on its own (that is the 15% rung).
    assert controlled.weights == portfolio.weights
    freeze = [e for e in events if e.rule == FREEZE_RULE]
    assert freeze and freeze[0].detail["action"] == "freeze_adds"
    assert not [e for e in events if e.rule == LIQUIDATE_RULE]


def test_t12_liquidate_rung_clears_overlay_and_pins_core_to_floor() -> None:
    portfolio = _book_with_overlay()
    state = RiskState(target_vol=0.11, target_vol_floor=0.10)
    # 18% drawdown past the 15% line, and predicted vol above the pinned floor
    # so the tightened target actually bites the core.
    inputs = RiskInputs(
        predicted_annual_vol=0.20,
        portfolio_drawdown=0.18,
        asset_classes={"SPY": "equity", "XLK": "equity"},
    )

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    # Overlay sleeve gone to cash.
    assert "SSO" not in controlled.weights
    liq = [e for e in events if e.rule == LIQUIDATE_RULE]
    assert liq and liq[0].detail["overlay_cleared"] == ["SSO"]
    assert liq[0].detail["core_vol_target_floor"] == pytest.approx(0.10)

    # Core vol target pinned to the floor -> vol targeter scales equity to 0.10/0.20.
    vol = [e for e in events if e.rule == VOL_RULE]
    assert vol, "core should be shrunk by the pinned-floor vol target"
    assert controlled.weights["SPY"] == pytest.approx(0.30)
    assert controlled.weights["XLK"] == pytest.approx(0.05)

    # Only ever de-risked, no leverage introduced.
    assert controlled.invested_weight() < portfolio.invested_weight()
    assert controlled.invested_weight() + controlled.cash_weight == pytest.approx(1.0)
