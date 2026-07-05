"""LLM satellite provider scaffolding for S-B / S-C (03 §5.3, 09 §1-2, ADR-24).

S-B (earnings direction score, Booth replication) and S-C (news drift score,
Lopez-Lira replication) are LLM-kind providers. They must:
  - declare a ``knowledge_cutoff`` (offline evaluation only credits post-cutoff
    samples; pre-cutoff is marked ``contaminated``, J3/ADR-24);
  - carry a position cap (S-B 10%, S-C 5%) enforced by the governance ladder;
  - never emit orders (ADR-22) — only scored inferences.

Actual scoring is produced by the M4 brief signal layer
(``yquant.brief.signal_provider``, lands with M4); here we fix the contract,
the model cards, the caps and the score→inference conversion so the strategy
and evaluation layers can integrate against a stable interface now.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from yquant.strategies.base import (
    ExplainContract,
    Inference,
    ModelCard,
)

if TYPE_CHECKING:
    from yquant.datasrc.protocols import DataRepo


@dataclass(frozen=True)
class LlmScore:
    """A raw per-symbol LLM score with its supporting evidence (from M4)."""

    symbol: str
    score: float  # signed direction score, roughly [-1, 1]
    confidence: float  # [0, 1]
    evidence: list[str]  # source links + rationale (09 §4 llm evidence)


# Signature of the M4 scoring callable injected into a provider.
Scorer = Callable[[date, list[str], "DataRepo"], list[LlmScore]]


class _LlmSatelliteProvider:
    """Shared base: turns injected M4 scores into contract-compliant inferences."""

    provider_id: str
    position_cap: float

    def __init__(self, scorer: Scorer, knowledge_cutoff: date) -> None:
        self._scorer = scorer
        self._knowledge_cutoff = knowledge_cutoff

    def predict(self, as_of: date, universe: list[str], repo: DataRepo) -> list[Inference]:
        scores = self._scorer(as_of, universe, repo)
        return [
            Inference(
                symbol=score.symbol,
                output=score.score,
                confidence=score.confidence,
                explain=ExplainContract(
                    kind="llm",
                    confidence=score.confidence,
                    regime_tag=self._regime_tag,
                    evidence=score.evidence,
                    caveats=[
                        "LLM score; pre-cutoff evaluation is contaminated (ADR-24)",
                        f"position cap {self.position_cap:.0%}",
                    ],
                ),
            )
            for score in scores
        ]

    _regime_tag: str = "llm_satellite"


class EarningsScoreProvider(_LlmSatelliteProvider):
    """S-B — LLM earnings-direction score (Booth replication), quarterly, cap 10%."""

    provider_id = "s_b_llm_earnings@0.1.0"
    position_cap = 0.10
    _regime_tag = "earnings_season"

    def model_card(self) -> ModelCard:
        return ModelCard(
            provider_id=self.provider_id,
            kind="llm",
            purpose="anonymised CoT earnings-direction score over covered universe (quarterly)",
            inputs=["earnings filings requirement segments", "anonymised financial deltas"],
            owner="research",
            knowledge_cutoff=self._knowledge_cutoff,
            known_limits=["replication of Booth; edge may not persist out of sample"],
            risks=["contamination if evaluated pre-cutoff", "short leg deferred to L2"],
            eval_report_ref="",
        )


class NewsDriftProvider(_LlmSatelliteProvider):
    """S-C — LLM news-drift score (Lopez-Lira replication), weekly, cap 5%."""

    provider_id = "s_c_llm_news@0.1.0"
    position_cap = 0.05
    _regime_tag = "news_drift"

    def model_card(self) -> ModelCard:
        return ModelCard(
            provider_id=self.provider_id,
            kind="llm",
            purpose="daily news sentiment score, strong-signal small book aggregated weekly",
            inputs=["daily news headlines/bodies", "prior close returns"],
            owner="research",
            knowledge_cutoff=self._knowledge_cutoff,
            known_limits=["decaying edge; retire on drift (09 §5)"],
            risks=["contamination if evaluated pre-cutoff", "high turnover if not aggregated"],
            eval_report_ref="",
        )
