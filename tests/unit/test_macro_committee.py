"""Unit tests for the M9 macro Layer-2/3: hawk/dove, schemas, committee (WP15)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from yquant.macro.committee import (
    CommitteeConfig,
    budget_theses,
    red_team_reject,
    run_committee,
)
from yquant.macro.hawk_dove import (
    CALIBRATION_MAX_MAD,
    build_calibration_set,
    calibrate,
    run_calibration,
    score_hawk_dove,
)
from yquant.macro.schemas import (
    MacroEventCard,
    RiskDashboardItem,
    ThesisProposal,
    is_machine_readable_condition,
)
from yquant.risk.state_machine import RegimeState


def _thesis(
    *,
    ticker: str = "MCHI",
    direction: str = "long",
    weight: float = 0.04,
    invalidation: str = "MCHI closes below 45",
) -> ThesisProposal:
    return ThesisProposal(
        thesis=f"{ticker} tactical view",
        global_rationale="global driver with a clear transmission channel",
        us_ticker=ticker,
        direction=direction,  # type: ignore[arg-type]
        entry_condition=f"{ticker} reclaims 50dma at 50",
        invalidation_condition=invalidation,
        weight=weight,
        time_limit_days=60,
        author="analyst",
    )


# ---- hawk/dove scorer + calibration ---------------------------------------


def test_score_hawk_dove_reads_hawkish_and_dovish() -> None:
    assert score_hawk_dove("We anticipate further tightening and additional rate hikes.") == 2
    assert score_hawk_dove("The committee expects rate cuts and will ease policy.") == -2
    assert score_hawk_dove("Decisions remain data dependent going forward.") == 0


def test_score_hawk_dove_dovish_tiebreak() -> None:
    # Balanced hawkish + dovish evidence resolves dovish (quarterly dovish bias):
    # +1 hawkish and -1 dovish net to 0, and the tie-break pulls it to -1.
    text = "Inflation remains elevated, but the labor market cooling continues."
    assert score_hawk_dove(text) == -1


def test_score_hawk_dove_clamps_to_five_tiers() -> None:
    text = (
        "Further tightening, additional rate hikes, raise rates, restrictive stance."
    )
    assert score_hawk_dove(text) == 2


def test_calibration_set_is_balanced_30() -> None:
    samples = build_calibration_set()
    assert len(samples) == 30
    tiers = [s.expected_tier for s in samples]
    for tier in (-2, -1, 0, 1, 2):
        assert tiers.count(tier) == 6


def test_calibration_passes_within_half_tier() -> None:
    report = run_calibration()
    assert report.total == 30
    assert report.mean_abs_deviation < CALIBRATION_MAX_MAD
    assert report.direction_accuracy >= 0.9
    assert report.passed is True
    assert report.mismatches == []


def test_calibration_fails_a_broken_scorer() -> None:
    report = calibrate(build_calibration_set(), scorer=lambda _text: 2)
    assert report.passed is False
    assert report.mean_abs_deviation >= CALIBRATION_MAX_MAD


def test_calibration_report_as_dict_is_json_safe() -> None:
    payload = run_calibration().as_dict()
    assert payload["passed"] is True
    assert isinstance(payload["mismatches"], list)


def test_calibrate_rejects_empty_set() -> None:
    with pytest.raises(ValueError):
        calibrate([])


# ---- MacroEventCard schema -------------------------------------------------


def test_macro_event_card_escalates_on_high_magnitude() -> None:
    card = MacroEventCard(
        event_id="mc-1",
        as_of=date(2024, 8, 5),
        source_type="cross_market",
        headline="USDJPY unwind spikes cross-asset volatility",
        hawk_dove=-1,
        channels=["risk appetite down", "carry unwind"],
        us_expression_map={"defensive": "raise cash, add TLT"},
        magnitude=5,
        half_life_days=10,
        confidence=0.6,
        evidence_urls=["https://www.federalreserve.gov/x"],
        contrarian_note="could be a one-day flush, not a regime change",
        prompt_version="macro_v1",
    )
    assert card.should_escalate is True


def test_macro_event_card_rejects_non_http_evidence() -> None:
    with pytest.raises(ValidationError):
        MacroEventCard(
            event_id="mc-2",
            as_of=date(2024, 8, 5),
            source_type="central_bank",
            headline="FOMC statement",
            hawk_dove=1,
            channels=["rates"],
            us_expression_map={"long": "SPY"},
            magnitude=3,
            half_life_days=5,
            confidence=0.5,
            evidence_urls=["ftp://sec.gov/x"],
            contrarian_note="note",
            prompt_version="macro_v1",
        )


# ---- committee: red team + budgeter ---------------------------------------


def test_is_machine_readable_condition() -> None:
    assert is_machine_readable_condition("VIX > 30")
    assert is_machine_readable_condition("SPY loses 200dma at 420")
    assert not is_machine_readable_condition("if things get worse")
    assert not is_machine_readable_condition("below the trend")  # no number


def test_red_team_rejects_icebox_ticker() -> None:
    verdict = red_team_reject(
        _thesis(ticker="TQQQ"), regime_state=RegimeState.RISK_ON, config=CommitteeConfig()
    )
    assert verdict is not None
    assert verdict.rule == "icebox_ticker"


def test_red_team_vetoes_long_in_crisis() -> None:
    verdict = red_team_reject(
        _thesis(direction="long"),
        regime_state=RegimeState.CRISIS,
        config=CommitteeConfig(),
    )
    assert verdict is not None
    assert verdict.rule == "regime_veto_long"


def test_red_team_allows_defensive_in_crisis() -> None:
    verdict = red_team_reject(
        _thesis(direction="defensive", ticker="TLT", invalidation="TLT closes below 90"),
        regime_state=RegimeState.CRISIS,
        config=CommitteeConfig(),
    )
    assert verdict is None


def test_budget_caps_single_name_to_five_percent() -> None:
    entries, rejected = budget_theses(
        [_thesis(ticker="MCHI", weight=0.09)], config=CommitteeConfig()
    )
    assert len(entries) == 1
    assert entries[0].weight == pytest.approx(0.05)
    assert rejected == []


def test_budget_merges_same_direction_same_ticker() -> None:
    entries, _ = budget_theses(
        [_thesis(ticker="EWJ", weight=0.02), _thesis(ticker="EWJ", weight=0.02)],
        config=CommitteeConfig(),
    )
    assert len(entries) == 1
    assert entries[0].weight == pytest.approx(0.04)


def test_budget_trims_and_rejects_when_total_cap_exhausted() -> None:
    theses = [
        _thesis(ticker="AAA", weight=0.05),
        _thesis(ticker="BBB", weight=0.05),
        _thesis(ticker="CCC", weight=0.05),
    ]
    entries, rejected = budget_theses(theses, config=CommitteeConfig())
    total = sum(e.weight for e in entries)
    assert total <= 0.10 + 1e-9
    assert any(r.rule == "overlay_budget_exhausted" for r in rejected)


def test_run_committee_full_pass() -> None:
    dashboard = [
        RiskDashboardItem(
            rank=1,
            risk_name="US recession",
            portfolio_exposure=0.6,
            defensive_expression="add TLT, raise cash",
        )
    ]
    theses = [
        _thesis(ticker="MCHI", weight=0.04),
        _thesis(ticker="TQQQ", weight=0.03),  # icebox -> rejected
        _thesis(ticker="EWZ", direction="long", weight=0.04),
    ]
    out = run_committee(
        as_of=date(2024, 3, 3),
        regime_state=RegimeState.RISK_ON,
        theses=theses,
        dashboard=dashboard,
    )
    tickers = {e.us_ticker for e in out.opportunity_book}
    assert tickers == {"MCHI", "EWZ"}
    assert out.total_overlay_weight <= 0.10 + 1e-9
    assert any(r.rule == "icebox_ticker" for r in out.rejected)
    assert out.regime_state == "RiskOn"
    assert out.dashboard[0].risk_name == "US recession"
