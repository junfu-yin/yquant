"""WP10 model-governance tests (09 §8 acceptance, all items).

Covers the four mandated exit gates:
  1. J3 contamination split is forced and correct on the constructed window
     (pre-cutoff → contaminated, post-cutoff → credited, rule → all credited).
  2. Non-trading provider eval lines: the Thesis-sentinel recall ≥ 90% on the
     dead-thesis set (hawk/dove + event-card lines live in their own modules).
  3. ModelCard / ExplainContract new-field envelope checks
     (knowledge_cutoff + data_dependencies mandatory for llm/ml_blackbox;
     knowledge_cutoff_note carried on the contract).
  4. Black-box performance dashboard buckets == the M9 four states.
Plus the panel roll-up / blocking verdict and the CLI `governance panel` e2e.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from yquant.cli import main
from yquant.governance import (
    EvalSample,
    build_governance_panel,
    build_thesis_recall_set,
    evaluate_offline,
    evaluate_thesis_recall,
    split_on_cutoff,
)
from yquant.governance.blackbox import (
    PSI_FREEZE,
    PSI_WARN,
    REGIME_BUCKETS,
    BehaviorTest,
    BucketObservation,
    DriftSentinel,
    FeatureDrift,
    build_blackbox_profile,
    population_stability_index,
)
from yquant.governance.demo import build_demo_governance_panel, demo_thesis_recall_summary
from yquant.governance.thesis_recall import RECALL_TARGET, run_thesis_recall
from yquant.risk.state_machine import RegimeState
from yquant.strategies.base import ExplainContract, ModelCard

# ------------------------------------------------------- J3 contamination ----


def _llm_card(cutoff: date | None = date(2024, 1, 1)) -> ModelCard:
    return ModelCard(
        provider_id="s_b_llm_earnings@0.1.0",
        kind="llm",
        purpose="earnings direction score",
        inputs=["filings"],
        owner="research",
        knowledge_cutoff=cutoff,
        data_dependencies=["daily_bars", "edgar_8k"],
    )


def _rule_card() -> ModelCard:
    return ModelCard(
        provider_id="c1@1.0.0",
        kind="rule",
        purpose="dual momentum",
        inputs=["prices"],
        owner="research",
    )


def test_split_on_cutoff_partitions_strictly_after() -> None:
    cutoff = date(2024, 1, 1)
    samples = [
        EvalSample("pre", date(2023, 12, 1), 0.1, 0.1),
        EvalSample("on", cutoff, 0.1, 0.1),  # on the boundary -> contaminated
        EvalSample("post", date(2024, 2, 1), 0.1, 0.1),
    ]
    credited, contaminated = split_on_cutoff(samples, cutoff)
    assert [s.sample_id for s in credited] == ["post"]
    assert [s.sample_id for s in contaminated] == ["pre", "on"]


def test_split_on_cutoff_none_credits_everything() -> None:
    samples = [
        EvalSample("a", date(2000, 1, 1), 0.1, 0.1),
        EvalSample("b", date(2025, 1, 1), 0.1, 0.1),
    ]
    credited, contaminated = split_on_cutoff(samples, None)
    assert len(credited) == 2
    assert contaminated == []


def test_evaluate_offline_marks_contaminated_ids_mandatorily() -> None:
    """09 §8: pre-cutoff samples MUST be stamped contaminated and never credited."""

    card = _llm_card(date(2024, 1, 1))
    samples = [
        EvalSample("leak-1", date(2023, 6, 1), 0.9, 0.9),
        EvalSample("leak-2", date(2023, 12, 1), -0.4, -0.5),
        EvalSample("fwd-1", date(2024, 3, 1), 0.5, 0.3),
        EvalSample("fwd-2", date(2024, 6, 1), -0.2, -0.4),
    ]
    report = evaluate_offline(card, samples)
    assert report.has_contamination is True
    assert set(report.contaminated_sample_ids) == {"leak-1", "leak-2"}
    assert report.contaminated.count == 2
    assert report.credited.count == 2
    payload = report.as_dict()
    assert payload["contaminated_sample_ids"] == ["leak-1", "leak-2"]
    assert payload["has_contamination"] is True
    assert "forbidden" in str(payload["note"])


def test_evaluate_offline_rule_provider_has_no_contamination() -> None:
    card = _rule_card()
    samples = [EvalSample("s", date(2010, 1, 1), 0.4, 0.5)]
    report = evaluate_offline(card, samples)
    assert report.has_contamination is False
    assert report.credited.count == 1
    assert report.contaminated_sample_ids == ()


def test_partition_hit_rate_and_mae() -> None:
    card = _rule_card()
    samples = [
        EvalSample("a", date(2020, 1, 1), 0.5, 0.4),  # same sign -> hit
        EvalSample("b", date(2020, 2, 1), 0.3, -0.2),  # opposite sign -> miss
    ]
    report = evaluate_offline(card, samples)
    assert report.credited.hit_rate == pytest.approx(0.5)
    assert report.credited.mean_abs_error == pytest.approx((0.1 + 0.5) / 2)


# --------------------------------------------------- ModelCard envelope ------


def test_model_card_llm_requires_cutoff() -> None:
    with pytest.raises(ValidationError):
        ModelCard(
            provider_id="x@0.1.0",
            kind="llm",
            purpose="p",
            inputs=["a"],
            owner="research",
            data_dependencies=["daily_bars"],
        )


def test_model_card_llm_requires_data_dependencies() -> None:
    with pytest.raises(ValidationError):
        ModelCard(
            provider_id="x@0.1.0",
            kind="llm",
            purpose="p",
            inputs=["a"],
            owner="research",
            knowledge_cutoff=date(2024, 1, 1),
        )


def test_model_card_ml_blackbox_requires_both() -> None:
    with pytest.raises(ValidationError):
        ModelCard(
            provider_id="nn@0.1.0",
            kind="ml_blackbox",
            purpose="p",
            inputs=["a"],
            owner="research",
        )
    ok = ModelCard(
        provider_id="nn@0.1.0",
        kind="ml_blackbox",
        purpose="p",
        inputs=["a"],
        owner="research",
        knowledge_cutoff=date(2024, 1, 1),
        data_dependencies=["daily_bars"],
    )
    assert ok.data_dependencies == ["daily_bars"]


def test_model_card_rule_needs_neither() -> None:
    card = _rule_card()
    assert card.knowledge_cutoff is None
    assert card.data_dependencies == []


def test_explain_contract_carries_knowledge_cutoff_note() -> None:
    contract = ExplainContract(
        kind="llm",
        confidence=0.7,
        regime_tag="earnings",
        knowledge_cutoff_note="fact sourced from today's 8-K, not parametric memory",
        caveats=["low sample"],
    )
    assert contract.knowledge_cutoff_note is not None
    # Optional for rule providers.
    rule = ExplainContract(kind="rule", confidence=0.9, regime_tag="trend", caveats=["rule"])
    assert rule.knowledge_cutoff_note is None


# ---------------------------------------------- black-box four-piece set -----


def test_performance_dashboard_buckets_match_m9_four_states() -> None:
    """09 §8: the performance dashboard is bucketed by the M9 four states."""

    assert REGIME_BUCKETS == (
        RegimeState.RISK_ON,
        RegimeState.NEUTRAL,
        RegimeState.RISK_OFF,
        RegimeState.CRISIS,
    )
    profile = build_blackbox_profile(
        "p@1",
        observations=[BucketObservation(RegimeState.RISK_ON, 0.5, 0.4)],
        top_features=[("f", 0.5)],
        feature_drifts=[FeatureDrift("f", 0.1)],
        ood_threshold=3.0,
    )
    bucket_regimes = tuple(b.regime for b in profile.performance.buckets)
    assert bucket_regimes == REGIME_BUCKETS
    assert len(profile.performance.buckets) == 4


def test_attribution_panel_is_descriptive_not_causal() -> None:
    profile = build_blackbox_profile(
        "p@1",
        observations=[],
        top_features=[("small", 0.1), ("big", -0.9)],
        feature_drifts=[],
        ood_threshold=3.0,
    )
    # Sorted by |contribution| descending.
    assert profile.attribution.top_features[0][0] == "big"
    assert "not causal" in profile.attribution.caveat


def test_drift_sentinel_ladder_and_ood_gate() -> None:
    sentinel = DriftSentinel(
        feature_drifts=(
            FeatureDrift("ok", 0.1),
            FeatureDrift("warn", 0.25),
            FeatureDrift("freeze", 0.35),
        ),
        ood_threshold=3.0,
    )
    assert FeatureDrift("ok", 0.1).status == "ok"
    assert FeatureDrift("warn", PSI_WARN + 0.01).status == "warn"
    assert FeatureDrift("freeze", PSI_FREEZE + 0.01).status == "freeze_candidate"
    assert sentinel.worst_status == "freeze_candidate"
    assert sentinel.forces_abstain(3.5) is True
    assert sentinel.forces_abstain(2.5) is False


def test_behavior_tests_execute_predicates() -> None:
    profile = build_blackbox_profile(
        "p@1",
        observations=[],
        top_features=[],
        feature_drifts=[],
        ood_threshold=3.0,
        behavior_tests=[
            BehaviorTest("g", "golden", "d", predicate=lambda: True),
            BehaviorTest("i", "invariance", "d", predicate=lambda: False),
        ],
    )
    assert profile.behavior_all_green is False
    outcomes = {r.test_id: r.passed for r in profile.behavior}
    assert outcomes == {"g": True, "i": False}


def test_population_stability_index_zero_for_identical() -> None:
    dist = [float(i) for i in range(100)]
    assert population_stability_index(dist, dist) == pytest.approx(0.0, abs=1e-9)
    shifted = [x + 50 for x in dist]
    assert population_stability_index(dist, shifted) > PSI_WARN


def test_population_stability_index_rejects_empty() -> None:
    with pytest.raises(ValueError):
        population_stability_index([], [1.0])


# ------------------------------------------- Thesis-sentinel recall line -----


def test_thesis_recall_set_shape() -> None:
    samples = build_thesis_recall_set()
    dead = [s for s in samples if s.truly_dead]
    alive = [s for s in samples if not s.truly_dead]
    assert len(dead) == 10
    assert len(alive) == 6


def test_thesis_recall_meets_target() -> None:
    """09 §8: the Thesis-sentinel recall on dead theses must clear ≥ 90%."""

    report = run_thesis_recall()
    assert report.dead_total == 10
    assert report.recall >= RECALL_TARGET
    assert report.passed is True
    assert report.false_negative == 0
    assert report.missed_ids == ()


def test_thesis_recall_report_as_dict() -> None:
    payload = evaluate_thesis_recall(build_thesis_recall_set()).as_dict()
    assert payload["recall_target"] == RECALL_TARGET
    assert payload["passed"] is True
    assert payload["dead_total"] == 10


def test_thesis_recall_rejects_empty() -> None:
    with pytest.raises(ValueError):
        evaluate_thesis_recall([])


# --------------------------------------------------- panel roll-up -----------


def test_governance_panel_orders_and_flags_contamination() -> None:
    llm = _llm_card(date(2024, 1, 1))
    rule = _rule_card()
    offline = {
        llm.provider_id: evaluate_offline(
            llm,
            [
                EvalSample("leak", date(2023, 1, 1), 0.5, 0.4),
                EvalSample("fwd", date(2024, 6, 1), 0.5, 0.4),
            ],
        )
    }
    panel = build_governance_panel([llm, rule], offline_reports=offline)
    # Ordered by provider_id.
    assert [r.card.provider_id for r in panel.rows] == sorted(
        [llm.provider_id, rule.provider_id]
    )
    assert panel.any_contaminated is True
    # Contamination alone does not block (there is a credited sample).
    assert panel.passed is True
    assert panel.blocked_provider_ids == ()


def test_governance_panel_blocks_fully_contaminated_provider() -> None:
    """A provider with zero credited samples is not promotable (09 §2/§6)."""

    llm = _llm_card(date(2024, 1, 1))
    offline = {
        llm.provider_id: evaluate_offline(
            llm, [EvalSample("leak", date(2023, 1, 1), 0.5, 0.4)]
        )
    }
    panel = build_governance_panel([llm], offline_reports=offline)
    assert panel.blocked_provider_ids == (llm.provider_id,)
    assert panel.passed is False


def test_governance_panel_blocks_on_red_behavior() -> None:
    rule = _rule_card()
    red = build_blackbox_profile(
        rule.provider_id,
        observations=[],
        top_features=[],
        feature_drifts=[],
        ood_threshold=3.0,
        behavior_tests=[BehaviorTest("t", "golden", "d", predicate=lambda: False)],
    )
    panel = build_governance_panel([rule], blackbox_profiles={rule.provider_id: red})
    assert panel.blocked_provider_ids == (rule.provider_id,)
    assert panel.passed is False


def test_governance_panel_marks_non_trading() -> None:
    rule = _rule_card()
    panel = build_governance_panel([rule], non_trading_ids=[rule.provider_id])
    assert panel.rows[0].is_trading is False


def test_demo_governance_panel_is_green_with_contamination() -> None:
    panel = build_demo_governance_panel()
    assert panel.passed is True
    assert panel.any_contaminated is True  # the two LLM satellites straddle the cutoff
    ids = {r.card.provider_id for r in panel.rows}
    assert "thesis_sentinel@1.0.0" in ids
    non_trading = {r.card.provider_id for r in panel.rows if not r.is_trading}
    assert non_trading == {
        "m9_hawk_dove@1.0.0",
        "m9_event_card_factory@1.0.0",
        "thesis_sentinel@1.0.0",
    }
    text = panel.render_text()
    assert "verdict: GREEN" in text
    assert "[contaminated]" in text


def test_demo_thesis_recall_summary_passes() -> None:
    summary = demo_thesis_recall_summary()
    assert summary["passed"] is True
    recall = summary["recall"]
    assert isinstance(recall, float)
    assert recall >= RECALL_TARGET


# --------------------------------------------------- CLI e2e -----------------


def test_governance_panel_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["governance", "panel"]) == 0
    out = capsys.readouterr().out
    assert "governance panel" in out
    assert "verdict: GREEN" in out
    assert "thesis_sentinel recall" in out


def test_governance_panel_cli_writes_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path = tmp_path / "governance.json"
    assert main(["governance", "panel", "--output", str(out_path)]) == 0
    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "thesis_recall" in text
    assert "providers" in text
    out = capsys.readouterr().out
    assert "governance_panel_artifact" in out
