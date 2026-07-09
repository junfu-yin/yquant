"""US-1~6 demo orchestration (03 §5.6 / §10).

Assembles a single deterministic payload that drives all six UI pages from the
*real* engines — the regime state machine, the Layer-3 committee, the M2 backtest
report, and the M5 discipline checklist — with no LLM in the loop and no network.
It exists so ``yquant ui demo`` (and the Streamlit shell) render a coherent story
that a test can pin byte-for-byte, exercising US-1 (today's brief), US-2/4
(opportunity + Thesis sentinel), US-3 (checklist gate + slippage), US-5 (a
JSON-safe payload the ledger could replay) and US-6 (the mandatory report
contract).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from yquant.backtest.report import build_report
from yquant.brief.schemas import EventCard
from yquant.datasrc.bars import repo_view
from yquant.discipline.checklist import ExecutionChecklist
from yquant.discipline.schemas import TradeProposal
from yquant.macro.committee import run_committee
from yquant.macro.schemas import CommitteeOutput, RiskDashboardItem, ThesisProposal
from yquant.qa.golden import build_golden_bars
from yquant.risk.state_machine import (
    RegimeInputs,
    RegimeMemory,
    RegimeReading,
    RegimeState,
    step,
)
from yquant.strategies.base import Layer, TargetPortfolio
from yquant.ui.viewmodels import (
    BacktestLabView,
    JournalRow,
    OpportunityRiskView,
    PortfolioRiskView,
    SystemHealthView,
    TodayBriefView,
    TradeJournalView,
    build_backtest_lab,
    build_journal_row,
    build_opportunity_risk,
    build_portfolio_risk,
    build_today_brief,
    build_trade_journal,
)

DEMO_AS_OF = date(2024, 3, 15)
_DEMO_WINDOW = "2024_carry"


@dataclass(frozen=True)
class DemoPayload:
    """The full six-page payload for the demo (US-1~6), JSON-safe end to end."""

    today_brief: TodayBriefView
    opportunity_risk: OpportunityRiskView
    portfolio_risk: PortfolioRiskView
    backtest_lab: BacktestLabView
    trade_journal: TradeJournalView
    system_health: SystemHealthView

    def to_dict(self) -> dict[str, Any]:
        return {
            "today_brief": self.today_brief.to_dict(),
            "opportunity_risk": self.opportunity_risk.to_dict(),
            "portfolio_risk": self.portfolio_risk.to_dict(),
            "backtest_lab": self.backtest_lab.to_dict(),
            "trade_journal": self.trade_journal.to_dict(),
            "system_health": self.system_health.to_dict(),
        }


def _demo_reading() -> RegimeReading:
    """A benign RiskOn-leaning reading so the committee admits long theses."""

    memory = RegimeMemory.initial(RegimeState.RISK_ON)
    _, reading = step(
        memory,
        RegimeInputs(
            spy_close=100.0,
            spy_ma_10m=90.0,
            pct_sectors_above_200d=0.72,
            hy_oas_percentile=0.25,
            hy_oas_change_3m_bp=-70.0,
            hyg_lqd_z=0.6,
            vix_level=12.5,
            vix_term_inversion_days=0,
            rsp_spy_trend_slope=0.15,
            pct_above_200d=0.7,
            nfci=-0.35,
            nfci_change=-0.1,
            curve_10y_3m=0.6,
            usd_change_3m=0.0,
        ),
    )
    return reading


def _demo_event_cards() -> list[EventCard]:
    return [
        EventCard(
            symbol="AAPL",
            market="us",
            source_type="announcement",
            event_type="业绩财报",
            severity=5,
            direction="利多",
            one_line="AAPL 季报超预期，服务业务加速",
            key_numbers=["EPS 2.18 vs 2.10", "服务 +14%"],
            rationale="services momentum beat and guidance raised",
            source_url="https://www.sec.gov/aapl-8k",
            prompt_version="brief_v1",
        ),
        EventCard(
            symbol="NVDA",
            market="us",
            source_type="news",
            event_type="重大合同",
            severity=4,
            direction="利多",
            one_line="NVDA 数据中心大单落地",
            key_numbers=["合同 $2.5B"],
            rationale="hyperscaler capex order confirmed",
            source_url="https://www.sec.gov/nvda-8k",
            prompt_version="brief_v1",
        ),
        EventCard(
            symbol="XLF",
            market="us",
            source_type="price_action",
            event_type="异动提示",
            severity=3,
            direction="中性",
            one_line="金融板块横盘，利率预期反复",
            key_numbers=["板块 +0.1%"],
            rationale="range-bound ahead of the rate decision",
            source_url="https://example.com/xlf",
            prompt_version="brief_v1",
        ),
        EventCard(
            symbol="STK07",
            market="us",
            source_type="financial",
            event_type="监管调查",
            severity=4,
            direction="利空",
            one_line="STK07 遭监管问询",
            key_numbers=["涉及金额未披露"],
            rationale="regulatory inquiry disclosed after close",
            source_url="https://example.com/stk07",
            prompt_version="brief_v1",
        ),
    ]


def _demo_committee() -> CommitteeOutput:
    return run_committee(
        as_of=DEMO_AS_OF,
        regime_state=RegimeState.RISK_ON,
        theses=[
            ThesisProposal(
                thesis="AI 资本开支超预期",
                global_rationale="hyperscaler capex guidance keeps stepping up each quarter",
                us_ticker="SMH",
                direction="long",
                entry_condition="回踩 20 日线企稳买入",
                invalidation_condition="SMH < 210",
                weight=0.05,
                time_limit_days=45,
                author="analyst",
            ),
            ThesisProposal(
                thesis="黄金对冲实际利率见顶",
                global_rationale="real yields plateau as the hiking cycle ends",
                us_ticker="GLD",
                direction="long",
                entry_condition="突破前高确认",
                invalidation_condition="GLD < 195",
                weight=0.04,
                time_limit_days=60,
                author="analyst",
            ),
        ],
        dashboard=[
            RiskDashboardItem(
                rank=1,
                risk_name="利率再通胀冲击",
                portfolio_exposure=0.45,
                defensive_expression="提高现金、缩久期",
            ),
            RiskDashboardItem(
                rank=2,
                risk_name="AI 资本开支证伪",
                portfolio_exposure=0.18,
                defensive_expression="收紧 Overlay 半导体敞口",
            ),
        ],
    )


def _demo_portfolio() -> TargetPortfolio:
    weights = {"SPY": 0.5, "TLT": 0.15, "GLD": 0.09, "SMH": 0.05}
    layers: dict[str, Layer] = {
        "SPY": "core",
        "TLT": "core",
        "GLD": "satellite",
        "SMH": "overlay",
    }
    return TargetPortfolio(as_of=DEMO_AS_OF, weights=weights, layers=layers, cash_weight=0.21)


def _demo_backtest_report() -> dict[str, Any]:
    bars = repo_view(build_golden_bars(_DEMO_WINDOW))
    weights = {"SPY": 0.5, "TLT": 0.2, "GLD": 0.1, "QQQ": 0.08}
    layers: dict[str, Layer] = {
        "SPY": "core",
        "TLT": "core",
        "GLD": "satellite",
        "QQQ": "overlay",
    }
    placed = {"done": False}

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if placed["done"] or not all(symbol in closes for symbol in weights):
            return None
        placed["done"] = True
        return TargetPortfolio(
            as_of=day, weights=dict(weights), layers=dict(layers), cash_weight=0.12
        )

    return build_report(
        bars=bars,
        target_provider=provider,
        initial_cash=50_000.0,
        benchmark_symbol="SPY",
    )


def _demo_journal_rows() -> list[JournalRow]:
    complete = ExecutionChecklist(
        triggered_by_rule=True,
        not_in_cooldown=True,
        within_single_name_cap=True,
        within_layer_budget=True,
        drawdown_allows_add=True,
        red_flags_reviewed=True,
        red_team_reviewed=True,
    )
    pending = ExecutionChecklist(
        triggered_by_rule=True,
        not_in_cooldown=True,
        within_single_name_cap=True,
        within_layer_budget=True,
        drawdown_allows_add=True,
        red_flags_reviewed=False,  # analyst has not read today's red flags yet
        red_team_reviewed=True,
    )
    executed = build_journal_row(
        _demo_proposal("SPY", layer="core", weight=0.5, side="buy"),
        complete,
        executed=True,
        slippage_bps=3.5,
    )
    blocked = build_journal_row(
        _demo_proposal("SMH", layer="overlay", weight=0.05, side="buy"),
        pending,
    )
    return [executed, blocked]


def _demo_proposal(symbol: str, *, layer: Layer, weight: float, side: str) -> TradeProposal:
    return TradeProposal(
        id=f"{symbol}-{DEMO_AS_OF.isoformat()}",
        created_at=datetime.combine(DEMO_AS_OF, time(13, 30)),
        strategy="C1" if layer == "core" else "overlay",
        symbol=symbol,
        side="buy" if side == "buy" else "sell",
        layer=layer,
        target_weight=weight,
        suggested_shares=10,
        position_rule="既定规则触发",
        invalidation_condition=f"{symbol} < 210" if symbol == "SMH" else "SPY < 400",
        red_team_note="反方：估值已计入乐观预期，若财报证伪则回撤显著",
        reason="system signal",
        related_events=[],
        status="pending",
    )


def _demo_system_health() -> SystemHealthView:
    return SystemHealthView(
        as_of=DEMO_AS_OF,
        p_metrics={
            "P1_accounting_conservation": "PASS",
            "P6_digest_reproducible": "PASS",
            "P10_state_machine_availability": "PASS",
            "P11_layer_budget": "PASS",
        },
        data_freshness={
            "daily_bars": "fresh (as of 2024-03-15 close)",
            "macro_series": "fresh (VIX, HY OAS, NFCI)",
        },
        job_runs=[
            {"job": "update", "status": "ok", "at": "2024-03-15T21:15:00Z"},
            {"job": "regime", "status": "ok", "at": "2024-03-15T21:20:00Z"},
        ],
        llm_usage={"provider": "deepseek", "calls_today": 0, "note": "demo runs LLM-free"},
    )


def build_demo_payload() -> DemoPayload:
    """Wire the real deterministic engines into the six-page demo payload (US-1~6)."""

    reading = _demo_reading()
    committee = _demo_committee()
    sentinel_metrics = {"SMH": 205.0, "GLD": 205.0}  # SMH below 210 -> sentinel fires
    report = _demo_backtest_report()
    rows = _demo_journal_rows()

    return DemoPayload(
        today_brief=build_today_brief(
            as_of=DEMO_AS_OF, reading=reading, event_cards=_demo_event_cards()
        ),
        opportunity_risk=build_opportunity_risk(
            committee=committee, sentinel_metrics=sentinel_metrics
        ),
        portfolio_risk=build_portfolio_risk(
            as_of=DEMO_AS_OF,
            portfolio=_demo_portfolio(),
            nav=1.082,
            benchmark_nav=1.041,
            drawdown=-0.037,
            risk_events=[
                {"rule": "vol_target", "detail": {"scale": 0.95}},
            ],
        ),
        backtest_lab=build_backtest_lab(report),
        trade_journal=build_trade_journal(DEMO_AS_OF, rows),
        system_health=_demo_system_health(),
    )
