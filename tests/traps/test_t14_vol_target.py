from datetime import date

from yquant.risk import RiskInputs, RiskState, apply_risk_controls
from yquant.risk.vol_target import RULE as VOL_RULE
from yquant.strategies.base import TargetPortfolio


def _equity_portfolio() -> TargetPortfolio:
    return TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.4, "QQQ": 0.4},
        layers={"SPY": "core", "QQQ": "core"},
        cash_weight=0.2,
    )


def test_t14_vol_targeter_scales_down_equity_on_high_vol() -> None:
    """T14: injected high vol > target*1.15 → equity weights scaled down only."""

    portfolio = _equity_portfolio()
    state = RiskState(target_vol=0.11)
    # Predicted vol 22% is 2x the 11% target, well above the 1.15x trigger.
    inputs = RiskInputs(
        predicted_annual_vol=0.22,
        asset_classes={"SPY": "equity", "QQQ": "equity"},
    )

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    # scale = 0.11 / 0.22 = 0.5 → each equity weight halved.
    assert controlled.weights["SPY"] == 0.2
    assert controlled.weights["QQQ"] == 0.2
    # Only reduced, never added; freed weight went to cash; no leverage.
    assert controlled.cash_weight > portfolio.cash_weight
    assert controlled.invested_weight() < portfolio.invested_weight()
    assert abs(controlled.invested_weight() + controlled.cash_weight - 1.0) < 1e-9
    assert any(e.rule == VOL_RULE for e in events)


def test_t14_vol_targeter_noop_when_within_budget() -> None:
    portfolio = _equity_portfolio()
    state = RiskState(target_vol=0.11)
    inputs = RiskInputs(
        predicted_annual_vol=0.10,
        asset_classes={"SPY": "equity", "QQQ": "equity"},
    )

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights == portfolio.weights
    assert events == []


def test_t14_vol_targeter_does_not_scale_non_equity() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.4, "IEF": 0.4},
        layers={"SPY": "core", "IEF": "core"},
        cash_weight=0.2,
    )
    state = RiskState(target_vol=0.11)
    inputs = RiskInputs(
        predicted_annual_vol=0.22,
        asset_classes={"SPY": "equity", "IEF": "bond"},
    )

    controlled, _ = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights["SPY"] == 0.2  # equity halved
    assert controlled.weights["IEF"] == 0.4  # bond untouched
