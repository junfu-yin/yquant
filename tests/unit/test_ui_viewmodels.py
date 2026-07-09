"""M6 UI view-model tests (03 §5.6): the mandatory "强制性 UI 测试".

The renderer is a thin shell; the invariants that matter — the six-item
checklist execution gate, the mandatory backtest-report contract, the Thesis
sentinel firing a machine-readable invalidation, and the P11 Overlay breach flag
— all live in the view models and are proven here without a browser.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import pytest

from yquant.brief.schemas import EventCard
from yquant.discipline.checklist import ExecutionChecklist
from yquant.discipline.schemas import TradeProposal
from yquant.macro.committee import run_committee
from yquant.macro.schemas import (
    CommitteeOutput,
    OpportunityBookEntry,
    RiskDashboardItem,
    ThesisProposal,
)
from yquant.risk.state_machine import (
    RegimeInputs,
    RegimeMemory,
    RegimeReading,
    RegimeState,
    step,
)
from yquant.strategies.base import TargetPortfolio
from yquant.ui.viewmodels import (
    PAGE_TITLES,
    ReportContractError,
    WeatherPanel,
    build_backtest_lab,
    build_journal_row,
    build_opportunity_risk,
    build_portfolio_risk,
    build_today_brief,
    build_trade_journal,
    evaluate_thesis,
)

AS_OF = date(2024, 3, 15)


def _reading() -> RegimeReading:
    memory = RegimeMemory.initial(RegimeState.NEUTRAL)
    _, reading = step(
        memory,
        RegimeInputs(
            spy_close=100.0,
            spy_ma_10m=90.0,
            pct_sectors_above_200d=0.7,
            hy_oas_percentile=0.3,
            hy_oas_change_3m_bp=-60.0,
            hyg_lqd_z=0.5,
            vix_level=13.0,
            vix_term_inversion_days=0,
            rsp_spy_trend_slope=0.1,
            pct_above_200d=0.7,
            nfci=-0.3,
            nfci_change=-0.1,
            curve_10y_3m=0.5,
            usd_change_3m=0.0,
        ),
    )
    return reading


def _card(symbol: str, severity: int) -> EventCard:
    return EventCard(
        symbol=symbol,
        market="us",
        source_type="announcement",
        event_type="业绩财报",
        severity=severity,
        direction="利多",
        one_line=f"{symbol} beat",
        key_numbers=["EPS +10%"],
        rationale="strong quarter",
        source_url="https://sec.gov/x",
        prompt_version="v1",
    )


def _proposal(symbol: str = "AAPL") -> TradeProposal:
    return TradeProposal(
        id=f"{symbol}-1",
        created_at=datetime.combine(AS_OF, time.min),
        strategy="C1",
        symbol=symbol,
        side="buy",
        layer="core",
        target_weight=0.1,
        suggested_shares=10,
        position_rule="rule",
        invalidation_condition="SPY < 400",
        red_team_note="could be a value trap",
        reason="signal",
        related_events=[],
        status="pending",
    )


def _complete_checklist() -> ExecutionChecklist:
    return ExecutionChecklist(
        triggered_by_rule=True,
        not_in_cooldown=True,
        within_single_name_cap=True,
        within_layer_budget=True,
        drawdown_allows_add=True,
        red_flags_reviewed=True,
        red_team_reviewed=True,
    )


# ---------------------------------------------------------------- Page 1 -----


def test_weather_panel_carries_all_five_pillars() -> None:
    panel = WeatherPanel.from_reading(_reading())
    assert set(panel.pillar_scores) == {
        "trend",
        "credit",
        "volatility",
        "breadth",
        "macro_liquidity",
    }
    assert panel.state == "Neutral"  # first reading, hysteresis holds the start state


def test_build_today_brief_top3_is_highest_severity() -> None:
    cards = [_card("AAA", 2), _card("BBB", 5), _card("CCC", 4), _card("DDD", 5)]
    brief = build_today_brief(as_of=AS_OF, reading=_reading(), event_cards=cards)
    top3_symbols = [c.symbol for c in brief.top3]
    assert top3_symbols == ["BBB", "DDD", "CCC"]  # sev 5,5,4 then symbol tiebreak
    assert len(brief.event_cards) == 4
    assert brief.to_dict()["as_of"] == AS_OF.isoformat()


# ---------------------------------------------------------------- Page 2 -----


def test_evaluate_thesis_fires_machine_readable_invalidation() -> None:
    entry = OpportunityBookEntry(
        thesis="semis rebound",
        global_rationale="global chip cycle turns up",
        us_ticker="SMH",
        direction="long",
        entry_condition="breakout above 200",
        invalidation_condition="SMH < 180",
        weight=0.05,
        time_limit_days=30,
        red_team_note="cyclical top risk",
    )
    dead = evaluate_thesis(entry, {"SMH": 170.0})
    assert dead.verdict == "invalidated"
    assert dead.close_suggestion is not None

    alive = evaluate_thesis(entry, {"SMH": 200.0})
    assert alive.verdict == "alive"
    assert alive.close_suggestion is None


def test_evaluate_thesis_missing_metric_stays_alive() -> None:
    entry = OpportunityBookEntry(
        thesis="gold hedge",
        global_rationale="real yields peak",
        us_ticker="GLD",
        direction="long",
        entry_condition="hold",
        invalidation_condition="GLD < 150",
        weight=0.03,
        time_limit_days=60,
        red_team_note="dollar strength risk",
    )
    row = evaluate_thesis(entry, {})  # no probe available
    assert row.verdict == "alive"


def test_build_opportunity_risk_rolls_up_committee() -> None:
    committee = run_committee(
        as_of=AS_OF,
        regime_state=RegimeState.RISK_ON,
        theses=[
            ThesisProposal(
                thesis="ai capex",
                global_rationale="hyperscaler spend accelerating",
                us_ticker="SMH",
                direction="long",
                entry_condition="dip buy",
                invalidation_condition="SMH < 180",
                weight=0.05,
                time_limit_days=45,
                author="analyst",
            )
        ],
        dashboard=[
            RiskDashboardItem(
                rank=1,
                risk_name="rate shock",
                portfolio_exposure=0.4,
                defensive_expression="raise cash",
            )
        ],
    )
    view = build_opportunity_risk(committee=committee, sentinel_metrics={"SMH": 170.0})
    assert view.total_overlay_weight == pytest.approx(0.05)
    assert view.thesis_sentinel[0].verdict == "invalidated"
    assert view.to_dict()["dashboard"][0]["risk_name"] == "rate shock"


# ---------------------------------------------------------------- Page 3 -----


def test_build_portfolio_risk_flags_overlay_breach() -> None:
    breaching = TargetPortfolio(
        as_of=AS_OF,
        weights={"SPY": 0.6, "SMH": 0.12},
        layers={"SPY": "core", "SMH": "overlay"},
        cash_weight=0.28,
    )
    view = build_portfolio_risk(
        as_of=AS_OF,
        portfolio=breaching,
        nav=1.05,
        benchmark_nav=1.02,
        drawdown=-0.03,
    )
    assert view.overlay_breach is True
    assert view.layer_weights["overlay"] == pytest.approx(0.12)


def test_build_portfolio_risk_within_budget_is_clean() -> None:
    within = TargetPortfolio(
        as_of=AS_OF,
        weights={"SPY": 0.6, "SMH": 0.08},
        layers={"SPY": "core", "SMH": "overlay"},
        cash_weight=0.32,
    )
    view = build_portfolio_risk(
        as_of=AS_OF, portfolio=within, nav=1.0, benchmark_nav=1.0, drawdown=0.0
    )
    assert view.overlay_breach is False


# ---------------------------------------------------------------- Page 4 -----


def _valid_report() -> dict[str, object]:
    return {
        "strategy": {"metrics": {"total_return": 0.1}},
        "benchmark": {"symbol": "SPY", "metrics": {"total_return": 0.08}},
        "cost_sensitivity": [
            {"tier": "0x", "metrics": {}},
            {"tier": "1x", "metrics": {}},
            {"tier": "2x", "metrics": {}},
        ],
        "walk_forward": [],
        "warnings": [],
    }


def test_build_backtest_lab_accepts_complete_report() -> None:
    view = build_backtest_lab(_valid_report())
    assert view.benchmark["symbol"] == "SPY"
    assert {row["tier"] for row in view.cost_sensitivity} == {"0x", "1x", "2x"}


def test_build_backtest_lab_rejects_missing_section() -> None:
    broken = _valid_report()
    del broken["benchmark"]
    with pytest.raises(ReportContractError):
        build_backtest_lab(broken)


def test_build_backtest_lab_rejects_missing_cost_tier() -> None:
    broken = _valid_report()
    broken["cost_sensitivity"] = [{"tier": "1x", "metrics": {}}]
    with pytest.raises(ReportContractError):
        build_backtest_lab(broken)


# ---------------------------------------------------------------- Page 5 -----


def test_journal_row_gate_blocks_execution_with_unmet_items() -> None:
    row = build_journal_row(_proposal(), ExecutionChecklist())
    assert row.can_execute is False
    assert row.unmet_checklist_items  # non-empty


def test_journal_row_allows_execution_when_checklist_complete() -> None:
    row = build_journal_row(
        _proposal(), _complete_checklist(), executed=True, slippage_bps=4.2
    )
    assert row.can_execute is True
    assert row.executed is True


def test_build_journal_row_refuses_executed_with_unmet_items() -> None:
    with pytest.raises(ValueError, match="cannot be executed"):
        build_journal_row(_proposal(), ExecutionChecklist(), executed=True)


def test_build_trade_journal_rolls_up_mean_slippage() -> None:
    rows = [
        build_journal_row(_proposal("AAA"), _complete_checklist(), executed=True, slippage_bps=2.0),
        build_journal_row(_proposal("BBB"), _complete_checklist(), executed=True, slippage_bps=6.0),
        build_journal_row(_proposal("CCC"), ExecutionChecklist()),  # no fill, no slippage
    ]
    view = build_trade_journal(AS_OF, rows)
    assert view.mean_slippage_bps == pytest.approx(4.0)


def test_build_trade_journal_no_fills_has_no_mean() -> None:
    view = build_trade_journal(AS_OF, [build_journal_row(_proposal(), ExecutionChecklist())])
    assert view.mean_slippage_bps is None


# ---------------------------------------------------------------- shared -----


def test_page_titles_are_the_six_pages() -> None:
    assert len(PAGE_TITLES) == 6


def test_committee_output_view_serializes_json_safe() -> None:
    committee = CommitteeOutput(as_of=AS_OF, regime_state="Neutral", prompt_version="v1")
    view = build_opportunity_risk(committee=committee)
    payload = view.to_dict()
    assert payload["regime_state"] == "Neutral"
    assert payload["opportunity_book"] == []


# ------------------------------------------------------------- demo (US-1~6) --


def test_demo_payload_covers_all_six_pages_and_is_json_safe() -> None:
    import json

    from yquant.ui.demo import build_demo_payload

    payload = build_demo_payload().to_dict()
    assert set(payload) == {
        "today_brief",
        "opportunity_risk",
        "portfolio_risk",
        "backtest_lab",
        "trade_journal",
        "system_health",
    }
    # US-5: the whole payload must serialize (a ledger could replay it verbatim).
    json.dumps(payload, ensure_ascii=False)


def test_demo_payload_wires_the_real_engines() -> None:
    from yquant.ui.demo import build_demo_payload

    payload = build_demo_payload().to_dict()
    # US-1: weather + Top-3 highest-severity cards.
    assert payload["today_brief"]["weather"]["state"] == "RiskOn"
    assert payload["today_brief"]["top3"][0]["symbol"] == "AAPL"
    # US-2/4: committee opportunity book + a fired Thesis sentinel (SMH < 210).
    fired = [r for r in payload["opportunity_risk"]["thesis_sentinel"] if r["verdict"] != "alive"]
    assert [r["us_ticker"] for r in fired] == ["SMH"]
    # US-6: mandatory report contract satisfied (0x/1x/2x + SPY benchmark).
    tiers = {t["tier"] for t in payload["backtest_lab"]["cost_sensitivity"]}
    assert tiers == {"0x", "1x", "2x"}
    assert payload["backtest_lab"]["benchmark"] is not None
    # US-3: one executed row, one blocked by the checklist gate.
    rows = payload["trade_journal"]["rows"]
    assert any(r["executed"] for r in rows)
    assert any(not r["can_execute"] for r in rows)


def test_ui_demo_cli_prints_and_writes_artifact(tmp_path: Path) -> None:
    import json

    from yquant.cli import main

    out_path = tmp_path / "ui_demo.json"
    code = main(["ui", "demo", "--output", str(out_path)])
    assert code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["today_brief"]["weather"]["state"] == "RiskOn"

