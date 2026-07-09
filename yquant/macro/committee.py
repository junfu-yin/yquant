"""Layer-3 opportunity/risk committee: analyst -> red team -> synthesis (03 §5.9).

The committee runs three deterministic steps over analyst-drafted theses:

1. **analyst** — validates each :class:`ThesisProposal` (schema + machine-readable
   invalidation is already enforced at construction);
2. **red team** — rejects theses that trip a deterministic guardrail: a missing
   machine-readable invalidation, a state-machine veto (Crisis / RiskOff refuse
   fresh *long* risk, ADR-32), or an icebox/inverse instrument;
3. **synthesis** — packs the survivors into the Overlay budget (10% total,
   individual cap) with a deterministic budgeter that trims rather than silently
   overspends, and assembles the risk dashboard + core tilts.

The LLM (in production) only *drafts* theses and prose; every gate here is a
rule, so "LLM 不产订单" holds and the whole pass is replayable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from yquant.macro.schemas import (
    CommitteeOutput,
    CoreTiltSuggestion,
    OpportunityBookEntry,
    RejectedThesis,
    RiskDashboardItem,
    ThesisProposal,
    is_machine_readable_condition,
)
from yquant.risk.state_machine import RegimeState

# Overlay sleeve budget (03 §5.9 / §7): 10% total, 5% single by default.
OVERLAY_TOTAL_CAP = 0.10
OVERLAY_SINGLE_CAP = 0.05

# Instruments the committee refuses regardless of thesis quality (ADR-31 icebox).
_ICEBOX_TICKERS = frozenset({"SQQQ", "TQQQ", "UPRO", "TMF", "SDS", "SPXU", "SH", "UVXY"})


@dataclass(frozen=True)
class CommitteeConfig:
    """Deterministic guardrail budget for one committee run."""

    overlay_total_cap: float = OVERLAY_TOTAL_CAP
    overlay_single_cap: float = OVERLAY_SINGLE_CAP
    icebox_tickers: frozenset[str] = _ICEBOX_TICKERS


def _regime_vetoes_long(state: RegimeState) -> bool:
    """RiskOff and Crisis refuse *fresh* long-risk theses (ADR-32 veto)."""

    return state in {RegimeState.RISK_OFF, RegimeState.CRISIS}


def red_team_reject(
    thesis: ThesisProposal,
    *,
    regime_state: RegimeState,
    config: CommitteeConfig,
) -> RejectedThesis | None:
    """Return a rejection if a deterministic guardrail refuses the thesis.

    The red team never argues about conviction; it only enforces rules. A
    ``None`` return means the thesis survives to the budgeter.
    """

    ticker = thesis.us_ticker
    if ticker in config.icebox_tickers:
        return RejectedThesis(
            thesis=thesis.thesis, us_ticker=ticker, rule="icebox_ticker", detail=ticker
        )
    if not is_machine_readable_condition(thesis.invalidation_condition):
        return RejectedThesis(
            thesis=thesis.thesis,
            us_ticker=ticker,
            rule="invalidation_not_machine_readable",
            detail=thesis.invalidation_condition,
        )
    if thesis.direction == "long" and _regime_vetoes_long(regime_state):
        return RejectedThesis(
            thesis=thesis.thesis,
            us_ticker=ticker,
            rule="regime_veto_long",
            detail=regime_state.value,
        )
    return None


def _merge_same_direction(theses: Sequence[ThesisProposal]) -> list[ThesisProposal]:
    """Merge same-ticker + same-direction theses (03 §5.9 "同向合并").

    Weights add (capped later); the strongest-conviction wording (longest
    rationale) wins the descriptive fields so the merged entry stays honest.
    """

    merged: dict[tuple[str, str], ThesisProposal] = {}
    order: list[tuple[str, str]] = []
    for thesis in theses:
        key = (thesis.us_ticker, thesis.direction)
        if key not in merged:
            merged[key] = thesis
            order.append(key)
            continue
        existing = merged[key]
        winner = max((existing, thesis), key=lambda t: len(t.global_rationale))
        merged[key] = winner.model_copy(
            update={"weight": min(1.0, existing.weight + thesis.weight)}
        )
    return [merged[key] for key in order]


def budget_theses(
    theses: Sequence[ThesisProposal],
    *,
    config: CommitteeConfig,
) -> tuple[list[OpportunityBookEntry], list[RejectedThesis]]:
    """Pack surviving theses into the Overlay budget with a deterministic trim.

    Same-direction duplicates are merged first. Each entry is then clamped to the
    single-name cap; entries are admitted in order until the total cap is hit,
    and any weight that would breach the total is trimmed to the remaining budget
    (an entry trimmed below a 0.5% floor is rejected rather than dusted in).
    """

    merged = _merge_same_direction(theses)
    entries: list[OpportunityBookEntry] = []
    rejected: list[RejectedThesis] = []
    remaining = config.overlay_total_cap

    for thesis in merged:
        capped = min(thesis.weight, config.overlay_single_cap)
        granted = min(capped, remaining)
        if granted < 0.005:
            rejected.append(
                RejectedThesis(
                    thesis=thesis.thesis,
                    us_ticker=thesis.us_ticker,
                    rule="overlay_budget_exhausted",
                    detail=f"remaining={remaining:.4f}",
                )
            )
            continue
        entries.append(
            OpportunityBookEntry(
                thesis=thesis.thesis,
                global_rationale=thesis.global_rationale,
                us_ticker=thesis.us_ticker,
                direction=thesis.direction,
                entry_condition=thesis.entry_condition,
                invalidation_condition=thesis.invalidation_condition,
                weight=round(granted, 6),
                time_limit_days=thesis.time_limit_days,
                red_team_note=f"passed red team under regime budget {config.overlay_total_cap:.0%}",
            )
        )
        remaining = round(remaining - granted, 6)

    return entries, rejected


def run_committee(
    *,
    as_of: date,
    regime_state: RegimeState,
    theses: Sequence[ThesisProposal],
    dashboard: Sequence[RiskDashboardItem] = (),
    core_tilts: Sequence[CoreTiltSuggestion] = (),
    prompt_version: str = "committee_v1",
    config: CommitteeConfig | None = None,
) -> CommitteeOutput:
    """Run analyst -> red team -> synthesis and assemble the committee output.

    ``theses`` are analyst drafts (already schema-valid). Red-team rejections and
    budget trims are recorded so the ledger keeps every refusal, not just the
    survivors.
    """

    config = config or CommitteeConfig()
    survivors: list[ThesisProposal] = []
    rejected: list[RejectedThesis] = []
    for thesis in theses:
        verdict = red_team_reject(thesis, regime_state=regime_state, config=config)
        if verdict is not None:
            rejected.append(verdict)
        else:
            survivors.append(thesis)

    entries, budget_rejects = budget_theses(survivors, config=config)
    rejected.extend(budget_rejects)

    return CommitteeOutput(
        as_of=as_of,
        regime_state=regime_state.value,
        dashboard=list(dashboard),
        opportunity_book=entries,
        core_tilts=list(core_tilts),
        rejected=rejected,
        prompt_version=prompt_version,
    )
