from datetime import date

from yquant.risk import RiskInputs, RiskState, apply_risk_controls
from yquant.risk.crowding import RULE as CROWD_RULE
from yquant.strategies.base import TargetPortfolio


def test_t15_crowding_sentinel_caps_add_to_illiquid_holding() -> None:
    """T15: liquidation > 20% of ADV → adding to that holding is capped."""

    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"ILLIQ": 0.30, "SPY": 0.40},
        layers={"ILLIQ": "satellite", "SPY": "core"},
        cash_weight=0.30,
    )
    state = RiskState(adv_liquidation_cap=0.20)
    # ILLIQ currently 10% of a 100k book = 10k. ADV 40k → 10k/40k = 25% > 20%.
    # Requested weight (30%) is an add above current 10% → must be capped to 10%.
    inputs = RiskInputs(
        predicted_annual_vol=0.08,
        adv={"ILLIQ": 40_000.0, "SPY": 5_000_000.0},
        position_value={"ILLIQ": 10_000.0, "SPY": 40_000.0},
        portfolio_value=100_000.0,
    )

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights["ILLIQ"] == 0.10  # capped to current weight
    assert controlled.weights["SPY"] == 0.40  # liquid → untouched
    assert controlled.cash_weight > portfolio.cash_weight
    crowd = [e for e in events if e.rule == CROWD_RULE]
    assert crowd and crowd[0].detail["flagged"][0]["symbol"] == "ILLIQ"


def test_t15_liquid_holding_can_be_added_to() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.60},
        layers={"SPY": "core"},
        cash_weight=0.40,
    )
    state = RiskState(adv_liquidation_cap=0.20)
    inputs = RiskInputs(
        predicted_annual_vol=0.08,
        adv={"SPY": 5_000_000.0},
        position_value={"SPY": 40_000.0},
        portfolio_value=100_000.0,
    )

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights["SPY"] == 0.60
    assert not [e for e in events if e.rule == CROWD_RULE]


def test_t15_noop_without_portfolio_value() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"ILLIQ": 0.30},
        layers={"ILLIQ": "satellite"},
        cash_weight=0.70,
    )
    state = RiskState()
    inputs = RiskInputs(
        predicted_annual_vol=0.08,
        adv={"ILLIQ": 40_000.0},
        position_value={"ILLIQ": 10_000.0},
        portfolio_value=0.0,
    )

    controlled, events = apply_risk_controls(portfolio, state, inputs, date(2024, 6, 3))

    assert controlled.weights == portfolio.weights
    assert events == []
