"""Deterministic governance-panel demo (09 §8 acceptance walkthrough).

Registers the providers the plan enumerates — the rule strategies (C1-C3 as one
card, S-A), the two LLM satellites (S-B/S-C), and the three *non-trading*
providers (hawk/dove scorer, event-card factory, Thesis sentinel) — then attaches
deterministic offline J3 reports and a black-box profile so the board renders the
full four-piece story with a live contamination flag. No network, no LLM.
"""

from __future__ import annotations

from datetime import date

from yquant.governance.blackbox import (
    BehaviorTest,
    BlackBoxProfile,
    BucketObservation,
    FeatureDrift,
    build_blackbox_profile,
)
from yquant.governance.evaluation import (
    EvalSample,
    OfflineEvaluationReport,
    evaluate_offline,
)
from yquant.governance.panel import ModelGovernancePanel, build_governance_panel
from yquant.governance.thesis_recall import run_thesis_recall
from yquant.risk.state_machine import RegimeState
from yquant.strategies.base import ModelCard
from yquant.strategies.satellite.llm_providers import (
    EarningsScoreProvider,
    NewsDriftProvider,
)

# A cutoff used by the demo LLM satellites; the offline set straddles it so the
# board shows both a credited (post-cutoff) and a contaminated (pre-cutoff) slice.
_DEMO_CUTOFF = date(2024, 1, 1)


def _demo_cards() -> list[ModelCard]:
    """The registered provider cards for the demo board."""

    rule_core = ModelCard(
        provider_id="c1_c3_core@1.0.0",
        kind="rule",
        purpose="core dual-momentum + trend gate + vol target (composite)",
        inputs=["monthly adjusted closes", "daily closes"],
        owner="research",
        known_limits=["whipsaw in choppy regimes"],
        risks=["momentum crash on sharp reversals"],
    )
    s_a = ModelCard(
        provider_id="s_a_sector_momentum@1.0.0",
        kind="rule",
        purpose="US GICS sector ETF 12-1 momentum, top 3 equal weight (monthly)",
        inputs=["monthly adjusted closes of GICS sector ETFs"],
        owner="research",
        known_limits=["single-factor; whipsaw in choppy regimes"],
        risks=["momentum crash on sharp reversals"],
    )
    s_b = EarningsScoreProvider(lambda _a, _u, _r: [], _DEMO_CUTOFF).model_card()
    s_c = NewsDriftProvider(lambda _a, _u, _r: [], _DEMO_CUTOFF).model_card()

    # Non-trading providers: registered + evaluated, hold no budget (09 §1 ◆).
    hawk_dove = ModelCard(
        provider_id="m9_hawk_dove@1.0.0",
        kind="rule",
        purpose="central-bank hawk/dove five-tier scorer (reference keyword model)",
        inputs=["central-bank statement text"],
        owner="research",
        known_limits=["keyword reference stands in for production LLM"],
        risks=["misses novel phrasing"],
    )
    event_factory = ModelCard(
        provider_id="m9_event_card_factory@1.0.0",
        kind="rule",
        purpose="8-K / macro event-card classifier + numeric verifier",
        inputs=["EDGAR 8-K item codes", "filing bodies"],
        owner="research",
        known_limits=["rule classification by item code"],
        risks=["hallucinated numbers rejected by the numeric gate"],
    )
    thesis_sentinel = ModelCard(
        provider_id="thesis_sentinel@1.0.0",
        kind="rule",
        purpose="daily machine-readable invalidation check for opportunity theses",
        inputs=["opportunity-book invalidation conditions", "current metric levels"],
        owner="research",
        known_limits=["single-comparator conditions only"],
        risks=["false negative (missed exit) is fatal — recall-gated"],
    )
    return [rule_core, s_a, s_b, s_c, hawk_dove, event_factory, thesis_sentinel]


def _demo_offline_reports(cards: list[ModelCard]) -> dict[str, OfflineEvaluationReport]:
    """Deterministic offline J3 reports for the two LLM satellites."""

    by_id = {c.provider_id: c for c in cards}
    reports: dict[str, OfflineEvaluationReport] = {}

    # A frozen labelled set that straddles the cutoff: pre-cutoff rows are
    # contaminated, post-cutoff rows are credited forward evidence.
    samples = [
        EvalSample("s-2023-06", date(2023, 6, 1), predicted=0.6, realized=0.4),
        EvalSample("s-2023-09", date(2023, 9, 1), predicted=-0.3, realized=-0.5),
        EvalSample("s-2023-12", date(2023, 12, 1), predicted=0.2, realized=-0.1),
        EvalSample("s-2024-03", date(2024, 3, 1), predicted=0.5, realized=0.3),
        EvalSample("s-2024-06", date(2024, 6, 1), predicted=-0.2, realized=-0.4),
        EvalSample("s-2024-09", date(2024, 9, 1), predicted=0.4, realized=0.5),
    ]
    for provider_id in ("s_b_llm_earnings@0.1.0", "s_c_llm_news@0.1.0"):
        reports[provider_id] = evaluate_offline(by_id[provider_id], samples)
    return reports


def _demo_blackbox(provider_id: str) -> BlackBoxProfile:
    """A four-piece profile for one LLM satellite, bucketed by the M9 states."""

    observations = [
        BucketObservation(RegimeState.RISK_ON, predicted=0.5, realized=0.4),
        BucketObservation(RegimeState.RISK_ON, predicted=0.3, realized=0.5),
        BucketObservation(RegimeState.NEUTRAL, predicted=0.1, realized=-0.1),
        BucketObservation(RegimeState.RISK_OFF, predicted=-0.4, realized=-0.3),
        BucketObservation(RegimeState.CRISIS, predicted=0.2, realized=-0.6),
    ]
    behavior = [
        BehaviorTest(
            test_id="golden-1",
            kind="golden",
            description="frozen input reproduces the frozen score",
            predicate=lambda: True,
        ),
        BehaviorTest(
            test_id="invariance-1",
            kind="invariance",
            description="ticker reorder does not move the score",
            predicate=lambda: True,
        ),
        BehaviorTest(
            test_id="directional-1",
            kind="directional",
            description="beat-and-raise sample scores non-negative",
            predicate=lambda: True,
        ),
    ]
    return build_blackbox_profile(
        provider_id,
        observations=observations,
        top_features=[("earnings_surprise", 0.42), ("guidance_delta", 0.28), ("volume", -0.11)],
        feature_drifts=[
            FeatureDrift("earnings_surprise", 0.08),
            FeatureDrift("guidance_delta", 0.22),
        ],
        ood_threshold=3.0,
        behavior_tests=behavior,
    )


def build_demo_governance_panel() -> ModelGovernancePanel:
    """Assemble the full demo governance board (09 §8 walkthrough)."""

    cards = _demo_cards()
    offline = _demo_offline_reports(cards)
    blackbox = {"s_b_llm_earnings@0.1.0": _demo_blackbox("s_b_llm_earnings@0.1.0")}
    non_trading = (
        "m9_hawk_dove@1.0.0",
        "m9_event_card_factory@1.0.0",
        "thesis_sentinel@1.0.0",
    )
    return build_governance_panel(
        cards,
        offline_reports=offline,
        blackbox_profiles=blackbox,
        non_trading_ids=non_trading,
    )


def demo_thesis_recall_summary() -> dict[str, object]:
    """Run the Thesis-sentinel recall line for the demo board (09 §2 ◆)."""

    return run_thesis_recall().as_dict()


__all__ = [
    "build_demo_governance_panel",
    "demo_thesis_recall_summary",
]
