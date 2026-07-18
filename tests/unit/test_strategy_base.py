from datetime import date

import pytest
from pydantic import ValidationError

from yquant.strategies.base import (
    ExplainContract,
    Inference,
    ModelCard,
    TargetPortfolio,
)


def test_target_portfolio_rejects_leverage() -> None:
    with pytest.raises(ValidationError):
        TargetPortfolio(
            as_of=date(2024, 6, 3),
            weights={"SPY": 0.8, "QQQ": 0.5},
            cash_weight=0.0,
        )


def test_target_portfolio_rejects_negative_weight() -> None:
    with pytest.raises(ValidationError):
        TargetPortfolio(as_of=date(2024, 6, 3), weights={"SPY": -0.1})


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf")])
def test_target_portfolio_rejects_non_finite_weight(weight: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        TargetPortfolio(as_of=date(2024, 6, 3), weights={"SPY": weight})


def test_target_portfolio_layer_weight() -> None:
    portfolio = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SPY": 0.5, "XLK": 0.2},
        layers={"SPY": "core", "XLK": "satellite"},
        cash_weight=0.3,
    )
    assert portfolio.layer_weight("core") == pytest.approx(0.5)
    assert portfolio.layer_weight("satellite") == pytest.approx(0.2)
    assert portfolio.invested_weight() == pytest.approx(0.7)


def test_model_card_requires_cutoff_for_llm() -> None:
    with pytest.raises(ValidationError):
        ModelCard(
            provider_id="s_b@0.1.0",
            kind="llm",
            purpose="earnings direction score",
            inputs=["filings"],
            owner="research",
        )


def test_model_card_rule_provider_allows_no_cutoff() -> None:
    card = ModelCard(
        provider_id="c1@1.0.0",
        kind="rule",
        purpose="dual momentum",
        inputs=["prices"],
        owner="research",
    )
    assert card.knowledge_cutoff is None


def test_explain_contract_requires_caveats() -> None:
    with pytest.raises(ValidationError):
        ExplainContract(kind="rule", confidence=0.5, regime_tag="trend", caveats=[])


def test_explain_contract_ml_requires_ood() -> None:
    with pytest.raises(ValidationError):
        ExplainContract(
            kind="ml_blackbox",
            confidence=0.5,
            regime_tag="trend",
            caveats=["low sample"],
        )


def test_inference_accepts_score_and_action() -> None:
    contract = ExplainContract(
        kind="rule",
        confidence=0.9,
        regime_tag="trend_high_vol",
        caveats=["rule-based, no forward-looking edge claimed"],
    )
    scored = Inference(symbol="SPY", output=0.42, confidence=0.9, explain=contract)
    action = Inference(symbol="SPY", output="buy", confidence=0.9, explain=contract)
    assert scored.output == 0.42
    assert action.output == "buy"
