from datetime import date

import pytest

from yquant.strategies.base import SignalProvider
from yquant.strategies.satellite import (
    EarningsScoreProvider,
    LlmScore,
    NewsDriftProvider,
    SectorMomentumProvider,
    sector_momentum_weights,
)


def _rising(base: float, step: float, n: int = 14) -> list[float]:
    return [base + step * i for i in range(n)]


def test_sector_momentum_picks_top_3() -> None:
    monthly = {
        "XLK": _rising(100, 6),
        "XLF": _rising(100, 5),
        "XLE": _rising(100, 4),
        "XLV": _rising(100, 1),
        "SPY": _rising(100, 9),  # not a sector ETF → ignored
    }
    portfolio = sector_momentum_weights(monthly, date(2024, 6, 3))

    assert set(portfolio.weights) == {"XLK", "XLF", "XLE"}
    assert all(w == pytest.approx(1 / 3) for w in portfolio.weights.values())
    assert all(layer == "satellite" for layer in portfolio.layers.values())


def test_sector_momentum_budget_scaling() -> None:
    monthly = {
        "XLK": _rising(100, 6),
        "XLF": _rising(100, 5),
        "XLE": _rising(100, 4),
    }
    portfolio = sector_momentum_weights(monthly, date(2024, 6, 3), budget=0.2)
    assert portfolio.invested_weight() == pytest.approx(0.2)


def test_sector_momentum_provider_is_rule_card() -> None:
    provider = SectorMomentumProvider()
    card = provider.model_card()
    assert card.kind == "rule"
    assert card.knowledge_cutoff is None
    assert isinstance(provider, SignalProvider)


def test_llm_providers_require_cutoff_and_have_caps() -> None:
    def _scorer(as_of: date, universe: list[str], repo: object) -> list[LlmScore]:
        return [LlmScore(symbol="AAPL", score=0.6, confidence=0.7, evidence=["url"])]

    s_b = EarningsScoreProvider(_scorer, knowledge_cutoff=date(2023, 12, 31))
    s_c = NewsDriftProvider(_scorer, knowledge_cutoff=date(2024, 3, 31))

    assert s_b.position_cap == 0.10
    assert s_c.position_cap == 0.05
    assert s_b.model_card().knowledge_cutoff == date(2023, 12, 31)
    assert s_c.model_card().kind == "llm"
    assert isinstance(s_b, SignalProvider)


def test_llm_provider_predict_emits_llm_inferences() -> None:
    def _scorer(as_of: date, universe: list[str], repo: object) -> list[LlmScore]:
        return [LlmScore(symbol="AAPL", score=0.6, confidence=0.7, evidence=["sec.gov/x"])]

    s_b = EarningsScoreProvider(_scorer, knowledge_cutoff=date(2023, 12, 31))
    inferences = s_b.predict(date(2024, 6, 3), ["AAPL"], repo=object())

    assert len(inferences) == 1
    inf = inferences[0]
    assert inf.symbol == "AAPL"
    assert inf.output == 0.6
    assert inf.explain.kind == "llm"
    assert any("contaminated" in c for c in inf.explain.caveats)
