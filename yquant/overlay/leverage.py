"""2x leverage-clause executor (03 §7 ADR-31, WP16).

The signed leverage clause is narrow and mechanical: only high-liquidity **2x
long** ETFs, ``<= 5%`` sleeve total and ``<= 3%`` single name, and a *three-
condition* open gate that must all hold —

  1. the M9 Layer-1 state machine is ``RiskOn`` (not merely "not stressed");
  2. the ticker trades above its 10-month moving average; and
  3. ``VIX < 20``.

A state downgrade force-clears every 2x position (the M8 regime gate already
halves in RiskOff and clears in Crisis; this executor refuses to *open* anywhere
but RiskOn). Every position carries a machine-readable invalidation and a hard
60-day review deadline, and its risk budget is charged at **twice** its market
weight (notional x2), never at face value.

This module is pure and deterministic: it decides *admissibility* and *budget*,
it never places an order (LLM/analysts draft, rules gate — 03 §7 red line).
Inverse and 3x tickers are refused by the universe filter in :func:`classify_2x`
before this executor ever sees them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from yquant.macro.schemas import condition_is_true, is_machine_readable_condition
from yquant.risk.state_machine import RegimeState

# The signed 2x sleeve caps (03 §7). Charged on *notional* (weight x leverage).
LEVERAGED_2X_TOTAL_CAP = 0.05
LEVERAGED_2X_SINGLE_CAP = 0.03
LEVERAGE_FACTOR = 2.0
VIX_OPEN_MAX = 20.0
REVIEW_DEADLINE_DAYS = 60

# The only 2x-long ETFs the clause admits (03 §7 examples; extend via config).
_KNOWN_2X_LONG = frozenset({"SSO", "QLD", "UGL", "DDM", "ROM", "UYG", "SAA"})
# 3x and inverse products are icebox / forbidden regardless of thesis quality.
_KNOWN_3X = frozenset({"TQQQ", "UPRO", "SPXL", "TMF", "SOXL", "UDOW", "TNA"})
_KNOWN_INVERSE = frozenset({"SQQQ", "SDS", "SPXU", "SH", "PSQ", "DOG", "RWM"})

# What the universe filter decided a ticker is.
Leverage2xKind = str  # "leveraged_2x_long" | "leveraged_3x" | "inverse" | "ordinary"


def classify_2x(ticker: str) -> Leverage2xKind:
    """Classify a ticker for the leverage clause (universe filter, T17).

    3x and inverse ETFs are refused outright; the recognised 2x-long names are
    admitted to the clause; everything else is an ordinary instrument (handled by
    the plain Overlay budgeter, not this executor).
    """

    key = ticker.strip().upper()
    if key in _KNOWN_3X:
        return "leveraged_3x"
    if key in _KNOWN_INVERSE:
        return "inverse"
    if key in _KNOWN_2X_LONG:
        return "leveraged_2x_long"
    return "ordinary"


@dataclass(frozen=True)
class LeverageOpenRequest:
    """A request to open a 2x-long sleeve position (drafted, not yet gated)."""

    ticker: str
    weight: float  # requested *market* weight of the position
    invalidation_condition: str
    as_of: date
    above_10m_ma: bool


@dataclass(frozen=True)
class LeverageRejection:
    """A refused 2x request, carrying the rule it broke (a risk_event detail)."""

    ticker: str
    rule: str
    detail: dict[str, float | str | bool | None] = field(default_factory=dict)


@dataclass(frozen=True)
class LeveragePosition:
    """An admitted 2x-long position with its notional budget and review deadline."""

    ticker: str
    weight: float
    notional_weight: float  # weight x LEVERAGE_FACTOR — the budgeted exposure
    invalidation_condition: str
    opened_on: date
    review_by: date

    def as_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "weight": round(self.weight, 6),
            "notional_weight": round(self.notional_weight, 6),
            "invalidation_condition": self.invalidation_condition,
            "opened_on": self.opened_on.isoformat(),
            "review_by": self.review_by.isoformat(),
        }


def three_condition_gate(
    *,
    regime: RegimeState,
    above_10m_ma: bool,
    vix_level: float,
) -> list[str]:
    """Return the failing open-conditions (empty list == all three hold).

    The clause opens only when *all* of ``RiskOn ∧ ticker>10mMA ∧ VIX<20`` are
    true; any missing condition is a named block so the ledger records *why* a
    2x request was refused.
    """

    failed: list[str] = []
    if regime is not RegimeState.RISK_ON:
        failed.append("regime_not_risk_on")
    if not above_10m_ma:
        failed.append("below_10m_ma")
    if vix_level >= VIX_OPEN_MAX:
        failed.append("vix_not_below_20")
    return failed


def open_leverage_position(
    request: LeverageOpenRequest,
    *,
    regime: RegimeState,
    vix_level: float,
    sleeve_notional_before: float = 0.0,
    total_cap: float = LEVERAGED_2X_TOTAL_CAP,
    single_cap: float = LEVERAGED_2X_SINGLE_CAP,
) -> tuple[LeveragePosition | None, LeverageRejection | None]:
    """Gate one 2x-long open request; return (position, None) or (None, rejection).

    Order of checks (first breach wins, so the rejection names the primary cause):
    universe filter -> machine-readable invalidation -> three-condition gate ->
    single-name notional cap -> sleeve total notional cap. Budget is charged on
    ``weight x 2`` (notional), never face value.
    """

    ticker = request.ticker.strip().upper()

    kind = classify_2x(ticker)
    if kind in {"leveraged_3x", "inverse"}:
        return None, LeverageRejection(
            ticker=ticker, rule=f"{kind}_forbidden", detail={"kind": kind}
        )
    if kind != "leveraged_2x_long":
        return None, LeverageRejection(
            ticker=ticker, rule="not_a_2x_long_etf", detail={"kind": kind}
        )

    if not is_machine_readable_condition(request.invalidation_condition):
        return None, LeverageRejection(
            ticker=ticker,
            rule="invalidation_not_machine_readable",
            detail={"invalidation_condition": request.invalidation_condition},
        )

    failed = three_condition_gate(
        regime=regime, above_10m_ma=request.above_10m_ma, vix_level=vix_level
    )
    if failed:
        return None, LeverageRejection(
            ticker=ticker,
            rule="open_conditions_unmet",
            detail={
                "failed": ",".join(failed),
                "regime": regime.value,
                "vix": round(vix_level, 4),
            },
        )

    notional = request.weight * LEVERAGE_FACTOR
    if notional > single_cap + 1e-9:
        return None, LeverageRejection(
            ticker=ticker,
            rule="leveraged_2x_single_cap",
            detail={"notional_weight": round(notional, 6), "cap": single_cap},
        )

    sleeve_after = sleeve_notional_before + notional
    if sleeve_after > total_cap + 1e-9:
        return None, LeverageRejection(
            ticker=ticker,
            rule="leveraged_2x_total_cap",
            detail={"sleeve_notional_after": round(sleeve_after, 6), "cap": total_cap},
        )

    return (
        LeveragePosition(
            ticker=ticker,
            weight=request.weight,
            notional_weight=notional,
            invalidation_condition=request.invalidation_condition,
            opened_on=request.as_of,
            review_by=request.as_of + timedelta(days=REVIEW_DEADLINE_DAYS),
        ),
        None,
    )


@dataclass(frozen=True)
class LeverageReviewRow:
    """A daily verdict for one open 2x position: hold / close (+ reason)."""

    ticker: str
    verdict: str  # hold | close
    reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {"ticker": self.ticker, "verdict": self.verdict, "reason": self.reason}


def review_leverage_positions(
    positions: list[LeveragePosition],
    *,
    on_date: date,
    regime: RegimeState,
    vix_level: float,
    metrics: dict[str, float],
) -> list[LeverageReviewRow]:
    """Daily 2x book review (S1/S2/S3): close on downgrade, invalidation, or deadline.

    A single position is closed when *any* of: the regime left RiskOn (S2 force-
    clear — a downgrade clears 2x), the machine-readable invalidation fired (S1),
    or the 60-day review deadline passed (S3). Otherwise it is held. Results are
    ordered by ticker for a deterministic, replayable ledger.
    """

    rows: list[LeverageReviewRow] = []
    for pos in sorted(positions, key=lambda p: p.ticker):
        reason: str | None = None
        if regime is not RegimeState.RISK_ON:
            reason = f"regime_downgrade:{regime.value}"
        elif vix_level >= VIX_OPEN_MAX:
            reason = "vix_not_below_20"
        elif condition_is_true(pos.invalidation_condition, pos.ticker, metrics):
            reason = "invalidation_hit"
        elif on_date >= pos.review_by:
            reason = "review_deadline"
        rows.append(
            LeverageReviewRow(
                ticker=pos.ticker,
                verdict="close" if reason else "hold",
                reason=reason,
            )
        )
    return rows
