"""M6 UI view models (03 §5.6): pure, JSON-safe builders for the six pages.

Streamlit is a thin renderer; every page's content is assembled here so it is
unit-testable without a browser (the SOW's "强制性 UI 测试"). The most important
invariant lives in :class:`JournalRow`: a proposal can only be marked executed
once all six §5.5 checklist items pass — the gate is data, not a UI callback, so
a test can prove it and the renderer cannot bypass it.

The six pages (03 §5.6):
  1. 今日简报    — global weather panel + event-card stream + Top-3 (US-1)
  2. 机会与风险  — risk dashboard + opportunity book + Thesis sentinel (US-2/4)
  3. 组合与风控  — three-layer budget levels, NAV vs SPY, drawdown, risk_events
  4. 回测实验室  — mandatory SPY comparison / cost tiers / walk-forward (US-6)
  5. 交易台账    — checklist gate + slippage closure + weekly review (US-3)
  6. 设置与系统健康 — P-metrics, data freshness, job logs, LLM usage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from yquant.brief.schemas import EventCard
from yquant.discipline.checklist import ExecutionChecklist
from yquant.discipline.schemas import TradeProposal
from yquant.macro.schemas import (
    CommitteeOutput,
    OpportunityBookEntry,
    condition_is_true,
)
from yquant.risk.state_machine import PILLARS, RegimeReading
from yquant.strategies.base import Layer, TargetPortfolio

# ------------------------------------------------------------------ Page 1 ---


@dataclass(frozen=True)
class WeatherPanel:
    """The global-weather panel: the committed regime plus its five pillars."""

    state: str
    composite: float
    pillar_scores: dict[str, int]
    stale_pillars: list[str]

    @classmethod
    def from_reading(cls, reading: RegimeReading) -> WeatherPanel:
        return cls(
            state=reading.state.value,
            composite=round(reading.composite, 6),
            pillar_scores={name: reading.pillar_scores.get(name, 0) for name in PILLARS},
            stale_pillars=list(reading.stale_pillars),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "composite": self.composite,
            "pillar_scores": dict(sorted(self.pillar_scores.items())),
            "stale_pillars": list(self.stale_pillars),
        }


@dataclass(frozen=True)
class EventCardView:
    """A single event card row rendered in the brief stream."""

    symbol: str
    event_type: str
    severity: int
    direction: str
    one_line: str
    source_url: str

    @classmethod
    def from_card(cls, card: EventCard) -> EventCardView:
        return cls(
            symbol=card.symbol,
            event_type=card.event_type,
            severity=card.severity,
            direction=card.direction,
            one_line=card.one_line,
            source_url=card.source_url,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "event_type": self.event_type,
            "severity": self.severity,
            "direction": self.direction,
            "one_line": self.one_line,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class TodayBriefView:
    """Page 1: weather panel + event stream + the Top-3 must-see cards (US-1)."""

    as_of: date
    weather: WeatherPanel
    event_cards: list[EventCardView]
    top3: list[EventCardView]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "weather": self.weather.to_dict(),
            "event_cards": [c.to_dict() for c in self.event_cards],
            "top3": [c.to_dict() for c in self.top3],
        }


def build_today_brief(
    *,
    as_of: date,
    reading: RegimeReading,
    event_cards: list[EventCard],
) -> TodayBriefView:
    """Assemble the Today's-Brief page; Top-3 = highest-severity cards (US-1)."""

    views = [EventCardView.from_card(c) for c in event_cards]
    ranked = sorted(views, key=lambda c: (-c.severity, c.symbol))
    return TodayBriefView(
        as_of=as_of,
        weather=WeatherPanel.from_reading(reading),
        event_cards=views,
        top3=ranked[:3],
    )


# ------------------------------------------------------------------ Page 2 ---


@dataclass(frozen=True)
class ThesisSentinelRow:
    """US-4: one open tactical thesis and its daily health verdict."""

    us_ticker: str
    thesis: str
    invalidation_condition: str
    verdict: str  # alive | invalidated
    close_suggestion: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "us_ticker": self.us_ticker,
            "thesis": self.thesis,
            "invalidation_condition": self.invalidation_condition,
            "verdict": self.verdict,
            "close_suggestion": self.close_suggestion,
        }


def evaluate_thesis(
    entry: OpportunityBookEntry,
    metrics: dict[str, float],
) -> ThesisSentinelRow:
    """Daily health check (US-4, S1): fire the machine-readable invalidation.

    ``metrics`` maps a probe name (typically the ticker) to its current level;
    the condition is parsed for a single comparator + threshold and evaluated.
    A dead thesis auto-produces a close suggestion (the first S1 sell trigger).
    A condition we cannot evaluate (missing metric) is treated as still alive so
    the sentinel never manufactures a phantom exit.
    """

    invalidated = condition_is_true(entry.invalidation_condition, entry.us_ticker, metrics)
    verdict = "invalidated" if invalidated else "alive"
    close = (
        f"close {entry.us_ticker}: invalidation hit ({entry.invalidation_condition})"
        if invalidated
        else None
    )
    return ThesisSentinelRow(
        us_ticker=entry.us_ticker,
        thesis=entry.thesis,
        invalidation_condition=entry.invalidation_condition,
        verdict=verdict,
        close_suggestion=close,
    )


@dataclass(frozen=True)
class OpportunityRiskView:
    """Page 2: risk dashboard + opportunity book + Thesis sentinel (US-2/4)."""

    as_of: date
    regime_state: str
    dashboard: list[dict[str, Any]]
    opportunity_book: list[dict[str, Any]]
    total_overlay_weight: float
    thesis_sentinel: list[ThesisSentinelRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "regime_state": self.regime_state,
            "dashboard": self.dashboard,
            "opportunity_book": self.opportunity_book,
            "total_overlay_weight": round(self.total_overlay_weight, 6),
            "thesis_sentinel": [row.to_dict() for row in self.thesis_sentinel],
        }


def build_opportunity_risk(
    *,
    committee: CommitteeOutput,
    sentinel_metrics: dict[str, float] | None = None,
) -> OpportunityRiskView:
    """Assemble the Opportunity & Risk page from a committee output (US-2/4)."""

    metrics = sentinel_metrics or {}
    sentinel = [evaluate_thesis(entry, metrics) for entry in committee.opportunity_book]
    return OpportunityRiskView(
        as_of=committee.as_of,
        regime_state=committee.regime_state,
        dashboard=[item.model_dump() for item in committee.dashboard],
        opportunity_book=[entry.model_dump() for entry in committee.opportunity_book],
        total_overlay_weight=committee.total_overlay_weight,
        thesis_sentinel=sentinel,
    )


# ------------------------------------------------------------------ Page 3 ---

_LAYERS: tuple[Layer, ...] = ("core", "satellite", "overlay")


@dataclass(frozen=True)
class PortfolioRiskView:
    """Page 3: three-layer budget levels, NAV vs SPY, drawdown, risk_events."""

    as_of: date
    layer_weights: dict[str, float]
    cash_weight: float
    nav: float
    benchmark_nav: float
    drawdown: float
    risk_events: list[dict[str, Any]]
    overlay_breach: bool  # P11: Overlay > 10% is an S1 alert.

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "layer_weights": {k: round(v, 6) for k, v in self.layer_weights.items()},
            "cash_weight": round(self.cash_weight, 6),
            "nav": round(self.nav, 6),
            "benchmark_nav": round(self.benchmark_nav, 6),
            "drawdown": round(self.drawdown, 6),
            "risk_events": self.risk_events,
            "overlay_breach": self.overlay_breach,
        }


def build_portfolio_risk(
    *,
    as_of: date,
    portfolio: TargetPortfolio,
    nav: float,
    benchmark_nav: float,
    drawdown: float,
    risk_events: list[dict[str, Any]] | None = None,
    overlay_cap: float = 0.10,
) -> PortfolioRiskView:
    """Assemble the Portfolio & Risk-control page (three-layer water levels)."""

    layer_weights: dict[str, float] = {
        str(layer): portfolio.layer_weight(layer) for layer in _LAYERS
    }
    return PortfolioRiskView(
        as_of=as_of,
        layer_weights=layer_weights,
        cash_weight=portfolio.cash_weight,
        nav=nav,
        benchmark_nav=benchmark_nav,
        drawdown=drawdown,
        risk_events=list(risk_events or []),
        overlay_breach=layer_weights["overlay"] > overlay_cap,
    )


# ------------------------------------------------------------------ Page 4 ---

_MANDATORY_REPORT_FIELDS = ("benchmark", "cost_sensitivity", "walk_forward", "warnings")


@dataclass(frozen=True)
class BacktestLabView:
    """Page 4: a backtest report is only publishable with its mandatory sections.

    T4/US-6: every report must carry a SPY buy-and-hold comparison, the 0/1x/2x
    cost tiers, an out-of-sample walk-forward slot and its warnings; a report
    missing any of these is refused here rather than shown half-formed.
    """

    strategy: dict[str, Any]
    benchmark: dict[str, Any]
    cost_sensitivity: list[dict[str, Any]]
    walk_forward: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "benchmark": self.benchmark,
            "cost_sensitivity": self.cost_sensitivity,
            "walk_forward": self.walk_forward,
            "warnings": self.warnings,
        }


class ReportContractError(ValueError):
    """A backtest report is missing a mandatory §5.6/US-6 section."""


def build_backtest_lab(report: dict[str, Any]) -> BacktestLabView:
    """Wrap an M2 report, enforcing the mandatory-section contract (US-6)."""

    missing = [key for key in _MANDATORY_REPORT_FIELDS if key not in report]
    if missing:
        raise ReportContractError(f"report missing mandatory sections: {missing}")
    tiers = report["cost_sensitivity"]
    tier_labels = {row.get("tier") for row in tiers}
    if not {"0x", "1x", "2x"}.issubset(tier_labels):
        raise ReportContractError("cost_sensitivity must cover the 0x/1x/2x tiers (T4)")
    return BacktestLabView(
        strategy=dict(report.get("strategy", {})),
        benchmark=dict(report["benchmark"]),
        cost_sensitivity=list(tiers),
        walk_forward=list(report["walk_forward"]),
        warnings=list(report["warnings"]),
    )


# ------------------------------------------------------------------ Page 5 ---


@dataclass(frozen=True)
class JournalRow:
    """Page 5: one proposal, its checklist gate, and (once filled) its slippage.

    ``can_execute`` is the hard gate (US-3): a proposal may only be marked
    executed when every §5.5 checklist item passes. The renderer disables the
    "mark executed" control on ``not can_execute`` — but the truth is here, so a
    unit test proves the gate independent of any UI.
    """

    proposal_id: str
    symbol: str
    side: str
    layer: str
    target_weight: float
    invalidation_condition: str
    red_team_note: str
    unmet_checklist_items: list[str]
    can_execute: bool
    executed: bool
    slippage_bps: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "symbol": self.symbol,
            "side": self.side,
            "layer": self.layer,
            "target_weight": round(self.target_weight, 6),
            "invalidation_condition": self.invalidation_condition,
            "red_team_note": self.red_team_note,
            "unmet_checklist_items": list(self.unmet_checklist_items),
            "can_execute": self.can_execute,
            "executed": self.executed,
            "slippage_bps": self.slippage_bps,
        }


def build_journal_row(
    proposal: TradeProposal,
    checklist: ExecutionChecklist,
    *,
    executed: bool = False,
    slippage_bps: float | None = None,
) -> JournalRow:
    """Build one journal row, enforcing the six-item checklist gate (US-3)."""

    unmet = checklist.unmet_items()
    can_execute = not unmet
    if executed and not can_execute:
        raise ValueError(
            f"proposal {proposal.id} cannot be executed with unmet checklist items: {unmet}"
        )
    return JournalRow(
        proposal_id=proposal.id,
        symbol=proposal.symbol,
        side=proposal.side,
        layer=proposal.layer,
        target_weight=proposal.target_weight,
        invalidation_condition=proposal.invalidation_condition,
        red_team_note=proposal.red_team_note,
        unmet_checklist_items=unmet,
        can_execute=can_execute,
        executed=executed,
        slippage_bps=slippage_bps,
    )


@dataclass(frozen=True)
class TradeJournalView:
    """Page 5: the full journal — rows plus the realised-slippage roll-up."""

    as_of: date
    rows: list[JournalRow]
    mean_slippage_bps: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "rows": [row.to_dict() for row in self.rows],
            "mean_slippage_bps": self.mean_slippage_bps,
        }


def build_trade_journal(as_of: date, rows: list[JournalRow]) -> TradeJournalView:
    """Assemble the trade-journal page and roll up realised slippage (US-3)."""

    slips = [row.slippage_bps for row in rows if row.slippage_bps is not None]
    mean = sum(slips) / len(slips) if slips else None
    return TradeJournalView(as_of=as_of, rows=rows, mean_slippage_bps=mean)


# ------------------------------------------------------------------ Page 6 ---


@dataclass(frozen=True)
class SystemHealthView:
    """Page 6: P-metric board, data freshness, job logs, and LLM usage."""

    as_of: date
    p_metrics: dict[str, Any] = field(default_factory=dict)
    data_freshness: dict[str, str] = field(default_factory=dict)
    job_runs: list[dict[str, Any]] = field(default_factory=list)
    llm_usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "p_metrics": self.p_metrics,
            "data_freshness": self.data_freshness,
            "job_runs": self.job_runs,
            "llm_usage": self.llm_usage,
        }


PAGE_TITLES: tuple[str, ...] = (
    "今日简报",
    "机会与风险",
    "组合与风控",
    "回测实验室",
    "交易台账",
    "设置与系统健康",
)
