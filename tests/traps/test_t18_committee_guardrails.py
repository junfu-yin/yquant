"""T18 — opportunity-book / committee guardrails (06 §2, 03 §5.9 red lines).

The plan makes three committee guarantees non-negotiable:

* an opportunity whose invalidation condition is missing or not machine-readable
  cannot be written (a Thesis sentinel must be able to fire on it);
* a fresh Overlay position beyond the 10% total sleeve is refused (trimmed to the
  remaining budget, or rejected when the budget is exhausted);
* the M9 Layer-1 state machine holds a veto — RiskOff/Crisis refuse *fresh long*
  theses (ADR-32), while defensive expressions remain admissible.

This trap drives those paths end-to-end through the deterministic committee so a
regression that softens any of them turns red.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from yquant.macro.committee import CommitteeConfig, run_committee
from yquant.macro.schemas import OpportunityBookEntry, ThesisProposal
from yquant.risk.state_machine import RegimeState


def _thesis(
    *,
    ticker: str,
    direction: str = "long",
    weight: float = 0.04,
    invalidation: str = "MCHI closes below 45",
) -> ThesisProposal:
    return ThesisProposal(
        thesis=f"{ticker} tactical view",
        global_rationale="global driver with a clear transmission channel to US",
        us_ticker=ticker,
        direction=direction,  # type: ignore[arg-type]
        entry_condition=f"{ticker} reclaims 50dma at 50",
        invalidation_condition=invalidation,
        weight=weight,
        time_limit_days=45,
        author="analyst",
    )


def test_t18_opportunity_requires_machine_readable_invalidation() -> None:
    # A vague invalidation cannot be written into the opportunity book at all.
    with pytest.raises(ValidationError):
        OpportunityBookEntry(
            thesis="India structural growth",
            global_rationale="demographics + capex cycle",
            us_ticker="INDA",
            direction="long",
            entry_condition="INDA breaks 50 on volume",
            invalidation_condition="if the story stops working",
            weight=0.03,
            time_limit_days=90,
            red_team_note="fine",
        )


def test_t18_machine_readable_invalidation_is_accepted() -> None:
    entry = OpportunityBookEntry(
        thesis="India structural growth",
        global_rationale="demographics + capex cycle",
        us_ticker="INDA",
        direction="long",
        entry_condition="INDA breaks 50 on volume",
        invalidation_condition="INDA closes below 46",
        weight=0.03,
        time_limit_days=90,
        red_team_note="crowded trade; size small",
    )
    assert entry.us_ticker == "INDA"


def test_t18_overlay_total_cap_is_enforced() -> None:
    # Three 5% requests cannot all fit the 10% sleeve; total stays <= cap.
    theses = [
        _thesis(ticker="AAA", weight=0.05, invalidation="AAA closes below 10"),
        _thesis(ticker="BBB", weight=0.05, invalidation="BBB closes below 10"),
        _thesis(ticker="CCC", weight=0.05, invalidation="CCC closes below 10"),
    ]
    out = run_committee(
        as_of=date(2024, 5, 1),
        regime_state=RegimeState.RISK_ON,
        theses=theses,
        config=CommitteeConfig(),
    )
    assert out.total_overlay_weight <= 0.10 + 1e-9
    assert any(r.rule == "overlay_budget_exhausted" for r in out.rejected)


def test_t18_single_name_cap_is_enforced() -> None:
    out = run_committee(
        as_of=date(2024, 5, 1),
        regime_state=RegimeState.RISK_ON,
        theses=[_thesis(ticker="EWZ", weight=0.09, invalidation="EWZ closes below 30")],
    )
    assert out.opportunity_book[0].weight == pytest.approx(0.05)


def test_t18_state_machine_vetoes_fresh_long_in_riskoff() -> None:
    out = run_committee(
        as_of=date(2024, 5, 1),
        regime_state=RegimeState.RISK_OFF,
        theses=[_thesis(ticker="MCHI", direction="long")],
    )
    assert out.opportunity_book == []
    assert any(r.rule == "regime_veto_long" for r in out.rejected)


def test_t18_defensive_thesis_survives_crisis() -> None:
    out = run_committee(
        as_of=date(2024, 5, 1),
        regime_state=RegimeState.CRISIS,
        theses=[
            _thesis(
                ticker="TLT",
                direction="defensive",
                weight=0.04,
                invalidation="TLT closes below 88",
            )
        ],
    )
    assert [e.us_ticker for e in out.opportunity_book] == ["TLT"]
    assert out.rejected == []
