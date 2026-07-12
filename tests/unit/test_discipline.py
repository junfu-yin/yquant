from datetime import date, datetime

import pytest

from yquant.discipline.checklist import ExecutionChecklist
from yquant.discipline.proposals import (
    ProposalMetadata,
    ProposalValidationError,
    build_proposals,
    suggested_shares,
)
from yquant.discipline.risk_rules import (
    DisciplineConfig,
    DisciplineState,
    check_cooldown,
    check_drawdown,
    check_position_caps,
    is_in_cooldown,
    triggers_cooldown,
)
from yquant.strategies.base import Layer, TargetPortfolio


def test_single_name_cap_blocks_oversized_buy() -> None:
    config = DisciplineConfig()
    violations = check_position_caps("buy", "AAPL", 0.20, 0.10, config)
    assert any(v.rule == "single_name_cap" and v.blocking for v in violations)


def test_industry_cap_blocks() -> None:
    config = DisciplineConfig()
    violations = check_position_caps("buy", "AAPL", 0.10, 0.40, config)
    assert any(v.rule == "industry_cap" and v.blocking for v in violations)


def test_sell_never_breaches_caps() -> None:
    config = DisciplineConfig()
    assert check_position_caps("sell", "AAPL", 0.99, 0.99, config) == []


def test_drawdown_strong_blocks_buy() -> None:
    config = DisciplineConfig()
    state = DisciplineState(drawdown=0.16)
    violations = check_drawdown("buy", state, config)
    assert violations and violations[0].rule == "drawdown_strong" and violations[0].blocking


def test_drawdown_alert_warns_but_not_blocking() -> None:
    config = DisciplineConfig()
    state = DisciplineState(drawdown=0.12)
    violations = check_drawdown("buy", state, config)
    assert violations and violations[0].rule == "drawdown_alert" and not violations[0].blocking


def test_cooldown_trigger_on_three_consecutive_losses() -> None:
    config = DisciplineConfig()
    assert triggers_cooldown(DisciplineState(recent_trade_pnl=[-1, -2, -3]), config) is True
    assert triggers_cooldown(DisciplineState(recent_trade_pnl=[-1, 2, -3]), config) is False
    assert triggers_cooldown(DisciplineState(recent_trade_pnl=[-1, -2]), config) is False


def test_cooldown_active_window() -> None:
    state = DisciplineState(cooldown_until=date(2024, 6, 10))
    assert is_in_cooldown(state, date(2024, 6, 5)) is True
    assert is_in_cooldown(state, date(2024, 6, 11)) is False
    violations = check_cooldown(state, date(2024, 6, 5), DisciplineConfig())
    assert violations and violations[0].rule == "cooldown" and not violations[0].blocking


def test_checklist_incomplete_lists_unmet() -> None:
    checklist = ExecutionChecklist()
    assert not checklist.is_complete()
    assert "off_plan_reason_required" in checklist.unmet_items()
    assert "within_position_and_layer_budget" in checklist.unmet_items()
    assert "red_team_reviewed" in checklist.unmet_items()


def test_checklist_off_plan_requires_reason() -> None:
    checklist = ExecutionChecklist(
        triggered_by_rule=False,
        not_in_cooldown=True,
        within_single_name_cap=True,
        within_layer_budget=True,
        drawdown_allows_add=True,
        red_flags_reviewed=True,
        red_team_reviewed=True,
    )
    assert not checklist.is_complete()  # missing off_plan_reason
    checklist.off_plan_reason = "manual rebalance"
    assert checklist.is_complete()


def test_checklist_complete_when_rule_triggered() -> None:
    checklist = ExecutionChecklist(
        triggered_by_rule=True,
        not_in_cooldown=True,
        within_single_name_cap=True,
        within_layer_budget=True,
        drawdown_allows_add=True,
        red_flags_reviewed=True,
        red_team_reviewed=True,
    )
    assert checklist.is_complete()
    assert checklist.to_json()["complete"] is True


def test_suggested_shares_whole_and_lot() -> None:
    assert suggested_shares(1000.0, 100.0) == 10.0
    assert suggested_shares(1050.0, 100.0) == 10.0  # floored to whole share
    assert suggested_shares(1050.0, 100.0, lot_size=5) == 10.0
    assert suggested_shares(950.0, 100.0, allow_fractional=True) == pytest.approx(9.5)


def test_build_proposals_diffs_weights() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"AAPL": 0.10, "MSFT": 0.05},
        layers={"AAPL": "satellite", "MSFT": "satellite"},
        cash_weight=0.85,
    )
    proposals = build_proposals(
        controlled,
        current_weights={"AAPL": 0.0, "MSFT": 0.05},  # MSFT unchanged → suppressed
        prices={"AAPL": 200.0, "MSFT": 400.0},
        portfolio_value=100_000.0,
        strategy="S-A",
        position_rule="single<=15%",
        proposal_metadata={
            "AAPL": ProposalMetadata(
                invalidation_condition="AAPL below 10-month trend",
                red_team_note="Momentum can reverse after crowded tech rallies.",
            )
        },
        now=datetime(2024, 6, 3, 9, 0),
    )
    assert len(proposals) == 1
    prop = proposals[0]
    assert prop.symbol == "AAPL"
    assert prop.side == "buy"
    assert prop.layer == "satellite"
    assert prop.invalidation_condition == "AAPL below 10-month trend"
    assert prop.red_team_note.startswith("Momentum")
    assert prop.suggested_shares == 50  # 0.10 * 100k / 200
    assert prop.status == "pending"


@pytest.mark.parametrize(
    ("current", "target", "side", "expected_shares"),
    [
        (0.00, 0.10, "buy", 50),
        (0.05, 0.10, "buy", 25),
        (0.10, 0.05, "sell", 25),
        (0.10, 0.00, "sell", 50),
    ],
)
def test_build_proposals_uses_incremental_weight_for_share_count(
    current: float,
    target: float,
    side: str,
    expected_shares: int,
) -> None:
    weights = {"AAPL": target} if target > 0 else {}
    layers: dict[str, Layer] = {"AAPL": "satellite"} if target > 0 else {}
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights=weights,
        layers=layers,
        cash_weight=1.0 - target,
    )

    proposals = build_proposals(
        controlled,
        current_weights={"AAPL": current},
        prices={"AAPL": 200.0},
        portfolio_value=100_000.0,
        strategy="regression",
        position_rule="incremental shares",
        min_weight_change=0.0,
        proposal_metadata={
            "AAPL": ProposalMetadata(
                invalidation_condition="AAPL < 180",
                red_team_note="The signal may reverse.",
                requested_layer="satellite",
            )
        },
        now=datetime(2024, 6, 3, 9, 0),
    )

    assert len(proposals) == 1
    assert proposals[0].side == side
    assert proposals[0].suggested_shares == expected_shares
    assert f"delta {target - current:+.4f}" in proposals[0].reason


def test_build_proposals_supports_explicit_lot_size_flooring() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"BRK.A": 0.10},
        layers={"BRK.A": "satellite"},
        cash_weight=0.90,
    )
    proposals = build_proposals(
        controlled,
        current_weights={},
        prices={"BRK.A": 350.0},
        portfolio_value=100_000.0,
        strategy="S-A",
        position_rule="single<=15%",
        lot_sizes={"BRK.A": 100},
        proposal_metadata={
            "BRK.A": ProposalMetadata(
                invalidation_condition="Thesis invalid if target leaves selected universe.",
                red_team_note="Lot sizing can prevent small accounts from expressing this target.",
            )
        },
        now=datetime(2024, 6, 3, 9, 0),
    )
    # 0.10 * 100k / 350 = 28.5 shares -> floored to lot 100 -> 0 shares.
    assert proposals[0].suggested_shares == 0


def test_build_proposals_requires_invalidation_condition() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"AAPL": 0.05},
        layers={"AAPL": "satellite"},
        cash_weight=0.95,
    )

    with pytest.raises(ProposalValidationError, match="invalidation_condition"):
        build_proposals(
            controlled,
            current_weights={},
            prices={"AAPL": 200.0},
            portfolio_value=100_000.0,
            strategy="S-A",
            position_rule="single<=15%",
            proposal_metadata={
                "AAPL": ProposalMetadata(
                    invalidation_condition=" ",
                    red_team_note="Counter-thesis present.",
                )
            },
        )


def test_build_proposals_requires_red_team_note() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"AAPL": 0.05},
        layers={"AAPL": "satellite"},
        cash_weight=0.95,
    )

    with pytest.raises(ProposalValidationError, match="red_team_note"):
        build_proposals(
            controlled,
            current_weights={},
            prices={"AAPL": 200.0},
            portfolio_value=100_000.0,
            strategy="S-A",
            position_rule="single<=15%",
            proposal_metadata={
                "AAPL": ProposalMetadata(
                    invalidation_condition="Signal leaves selected universe.",
                    red_team_note=" ",
                )
            },
        )


def test_build_proposals_rejects_3x_icebox_buy() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"TQQQ": 0.01},
        layers={"TQQQ": "overlay"},
        cash_weight=0.99,
    )

    with pytest.raises(ProposalValidationError) as exc:
        build_proposals(
            controlled,
            current_weights={},
            prices={"TQQQ": 60.0},
            portfolio_value=100_000.0,
            strategy="manual",
            position_rule="overlay<=10%",
            proposal_metadata={
                "TQQQ": ProposalMetadata(
                    invalidation_condition="3x thesis expires at close.",
                    red_team_note="3x is in icebox and path-dependent.",
                    instrument_kind="leveraged_3x",
                    is_system_signal=False,
                    requested_layer="overlay",
                )
            },
        )

    rules = {violation.rule for violation in exc.value.violations}
    assert rules == {"icebox_ticker", "leveraged_3x_not_allowed"}


def test_build_proposals_rejects_2x_single_cap_breach() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"SSO": 0.04},
        layers={"SSO": "core"},
        cash_weight=0.96,
    )

    with pytest.raises(ProposalValidationError) as exc:
        build_proposals(
            controlled,
            current_weights={},
            prices={"SSO": 80.0},
            portfolio_value=100_000.0,
            strategy="overlay-2x",
            position_rule="2x<=5%, single<=3%",
            proposal_metadata={
                "SSO": ProposalMetadata(
                    invalidation_condition="Exit if state leaves RiskOn.",
                    red_team_note="2x daily reset can decay in choppy markets.",
                    instrument_kind="leveraged_2x_long",
                    is_system_signal=True,
                    requested_layer="core",
                )
            },
        )

    assert {violation.rule for violation in exc.value.violations} == {
        "leveraged_2x_single_cap"
    }


def test_build_proposals_routes_meme_stock_to_overlay() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"GME": 0.03},
        layers={"GME": "satellite"},
        cash_weight=0.97,
    )
    proposals = build_proposals(
        controlled,
        current_weights={},
        prices={"GME": 25.0},
        portfolio_value=100_000.0,
        strategy="manual",
        position_rule="overlay<=10%",
        proposal_metadata={
            "GME": ProposalMetadata(
                invalidation_condition="Exit if social-volume spike fades for 2 sessions.",
                red_team_note="Meme flows reverse violently and are not a system signal.",
                instrument_kind="meme_stock",
                is_system_signal=False,
                requested_layer="satellite",
            )
        },
    )

    assert proposals[0].layer == "overlay"
    assert proposals[0].instrument_kind == "meme_stock"
