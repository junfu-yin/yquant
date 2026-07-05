from datetime import date, datetime

import pytest

from yquant.discipline.checklist import ExecutionChecklist
from yquant.discipline.proposals import build_proposals, suggested_shares
from yquant.discipline.risk_rules import (
    DisciplineConfig,
    DisciplineState,
    check_cooldown,
    check_drawdown,
    check_position_caps,
    is_in_cooldown,
    triggers_cooldown,
)
from yquant.strategies.base import TargetPortfolio


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


def test_checklist_off_plan_requires_reason() -> None:
    checklist = ExecutionChecklist(
        triggered_by_rule=False,
        not_in_cooldown=True,
        within_single_name_cap=True,
        drawdown_allows_add=True,
        red_flags_reviewed=True,
    )
    assert not checklist.is_complete()  # missing off_plan_reason
    checklist.off_plan_reason = "manual rebalance"
    assert checklist.is_complete()


def test_checklist_complete_when_rule_triggered() -> None:
    checklist = ExecutionChecklist(
        triggered_by_rule=True,
        not_in_cooldown=True,
        within_single_name_cap=True,
        drawdown_allows_add=True,
        red_flags_reviewed=True,
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
        now=datetime(2024, 6, 3, 9, 0),
    )
    assert len(proposals) == 1
    prop = proposals[0]
    assert prop.symbol == "AAPL"
    assert prop.side == "buy"
    assert prop.suggested_shares == 50  # 0.10 * 100k / 200
    assert prop.status == "pending"


def test_build_proposals_hk_lot_size() -> None:
    controlled = TargetPortfolio(
        as_of=date(2024, 6, 3),
        weights={"0700.HK": 0.10},
        layers={"0700.HK": "satellite"},
        cash_weight=0.90,
    )
    proposals = build_proposals(
        controlled,
        current_weights={},
        prices={"0700.HK": 350.0},
        portfolio_value=100_000.0,
        strategy="S-A",
        position_rule="single<=15%",
        lot_sizes={"0700.HK": 100},
        now=datetime(2024, 6, 3, 9, 0),
    )
    # 0.10 * 100k / 350 = 28.5 shares → floored to lot 100 → 0 shares.
    assert proposals[0].suggested_shares == 0
