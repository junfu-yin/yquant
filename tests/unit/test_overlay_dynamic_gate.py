from __future__ import annotations

from datetime import date
from pathlib import Path

from yquant.discipline.overlay_guardrails import OverlayExposure, validate_overlay_request
from yquant.discipline.proposals import (
    ProposalMetadata,
    ProposalValidationError,
    build_proposals,
)
from yquant.discipline.reject_ledger import record_proposal_rejection
from yquant.ledger import LedgerStore
from yquant.risk.regime import compute_risk_on
from yquant.strategies.base import TargetPortfolio


def _exposure() -> OverlayExposure:
    return OverlayExposure(
        overlay_weight_after=0.04,
        symbol_weight_after=0.02,
        leveraged_2x_weight_after=0.04,
    )


def test_2x_allowed_when_risk_on() -> None:
    regime = compute_risk_on(market_trend_ok=True, vix_level=15.0)
    violations = validate_overlay_request(
        symbol="SSO",
        instrument_kind="leveraged_2x_long",
        exposure=_exposure(),
        risk_regime=regime,
    )
    assert [v.rule for v in violations] == []


def test_2x_rejected_when_risk_off() -> None:
    regime = compute_risk_on(market_trend_ok=False, vix_level=15.0)
    violations = validate_overlay_request(
        symbol="SSO",
        instrument_kind="leveraged_2x_long",
        exposure=_exposure(),
        risk_regime=regime,
    )
    assert "leveraged_2x_risk_off" in {v.rule for v in violations}


def test_no_regime_keeps_static_behavior() -> None:
    # Backward compatibility: without a regime, a within-caps 2x request passes.
    violations = validate_overlay_request(
        symbol="SSO",
        instrument_kind="leveraged_2x_long",
        exposure=_exposure(),
    )
    assert violations == []


def _metadata() -> dict[str, ProposalMetadata]:
    return {
        "SSO": ProposalMetadata(
            invalidation_condition="close < 50",
            red_team_note="leverage decays in chop",
            instrument_kind="leveraged_2x_long",
            is_system_signal=False,
            requested_layer="overlay",
        )
    }


def test_build_proposals_rejects_2x_in_risk_off_and_ledgers(tmp_path: Path) -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 1, 3),
        weights={"SSO": 0.02},
        layers={"SSO": "overlay"},
        cash_weight=0.98,
    )
    risk_off = compute_risk_on(market_trend_ok=False, vix_level=30.0)

    store = LedgerStore(tmp_path / "yquant.db")
    store.bootstrap()

    try:
        build_proposals(
            controlled,
            current_weights={},
            prices={"SSO": 50.0},
            portfolio_value=100_000.0,
            strategy="overlay_test",
            position_rule="fixed",
            proposal_metadata=_metadata(),
            risk_regime=risk_off,
        )
    except ProposalValidationError as error:
        ids = record_proposal_rejection(store, error, as_of=date(2024, 1, 3))
    else:  # pragma: no cover - the request must be rejected
        raise AssertionError("expected a ProposalValidationError")

    events = store.list_risk_events()
    assert len(ids) == len(events) >= 1
    rules = {event.rule for event in events}
    assert "proposal_reject:leveraged_2x_risk_off" in rules


def test_record_generic_rejection_without_violations(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "yquant.db")
    store.bootstrap()
    error = ProposalValidationError("metadata missing", symbol="AAPL")

    ids = record_proposal_rejection(store, error, as_of=date(2024, 1, 3))

    events = store.list_risk_events()
    assert len(ids) == 1
    assert events[0].rule == "proposal_reject"
    assert events[0].detail["symbol"] == "AAPL"
