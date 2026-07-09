"""Paper opportunity book — a shadow-period tracker for tactical theses (WP16).

Before the Overlay sleeve trades real money it runs in *paper* mode: every
committee-approved opportunity is entered on a start date, the Thesis sentinel
checks it each session, and the book records — without ever placing an order —
when the thesis was invalidated (S1), hit its time limit (S3), or is still open
at the end of the shadow window. At the end of the window it emits statistics
(the "纸上机会簿在影子期跑通并出统计" Gate): counts, invalidation/expiry rates,
and the average holding period, all deterministic and replayable.

This is the forward-verification harness the plan requires for the tactical
layer's Kill/pivot judgement (K1'): if paper theses are systematically dead on
arrival, the sleeve is retired rather than shipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from yquant.macro.schemas import OpportunityBookEntry, condition_is_true

# A paper position ends one of three ways.
PaperOutcome = str  # "invalidated" | "expired" | "open"


@dataclass(frozen=True)
class PaperThesisResult:
    """One paper opportunity's lifecycle over the shadow window."""

    us_ticker: str
    thesis: str
    entered_on: date
    outcome: PaperOutcome
    closed_on: date | None
    holding_days: int
    close_reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "us_ticker": self.us_ticker,
            "thesis": self.thesis,
            "entered_on": self.entered_on.isoformat(),
            "outcome": self.outcome,
            "closed_on": self.closed_on.isoformat() if self.closed_on else None,
            "holding_days": self.holding_days,
            "close_reason": self.close_reason,
        }


@dataclass(frozen=True)
class PaperBookStats:
    """End-of-window statistics for the paper opportunity book."""

    entered: int
    invalidated: int
    expired: int
    still_open: int
    invalidation_rate: float
    mean_holding_days: float
    results: list[PaperThesisResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "entered": self.entered,
            "invalidated": self.invalidated,
            "expired": self.expired,
            "still_open": self.still_open,
            "invalidation_rate": round(self.invalidation_rate, 6),
            "mean_holding_days": round(self.mean_holding_days, 6),
            "results": [r.as_dict() for r in self.results],
        }


@dataclass(frozen=True)
class PaperEntry:
    """An opportunity entered into the paper book on a specific date."""

    entry: OpportunityBookEntry
    entered_on: date


def _track_one(
    entry: PaperEntry,
    sessions: list[tuple[date, dict[str, float]]],
) -> PaperThesisResult:
    """Replay one paper thesis across the (ordered) shadow sessions.

    The first session on/after the entry date at which the machine-readable
    invalidation fires closes it (S1). If it never fires, the time limit
    (``entered_on + time_limit_days``) expires it (S3). Otherwise it is still
    open at the window's end.
    """

    ticker = entry.entry.us_ticker
    deadline_ord = entry.entered_on.toordinal() + entry.entry.time_limit_days
    for day, metrics in sessions:
        if day < entry.entered_on:
            continue
        if condition_is_true(entry.entry.invalidation_condition, ticker, metrics):
            return PaperThesisResult(
                us_ticker=ticker,
                thesis=entry.entry.thesis,
                entered_on=entry.entered_on,
                outcome="invalidated",
                closed_on=day,
                holding_days=day.toordinal() - entry.entered_on.toordinal(),
                close_reason="invalidation_hit",
            )
        if day.toordinal() >= deadline_ord:
            return PaperThesisResult(
                us_ticker=ticker,
                thesis=entry.entry.thesis,
                entered_on=entry.entered_on,
                outcome="expired",
                closed_on=day,
                holding_days=day.toordinal() - entry.entered_on.toordinal(),
                close_reason="time_limit",
            )

    last_day = sessions[-1][0] if sessions else entry.entered_on
    return PaperThesisResult(
        us_ticker=ticker,
        thesis=entry.entry.thesis,
        entered_on=entry.entered_on,
        outcome="open",
        closed_on=None,
        holding_days=max(0, last_day.toordinal() - entry.entered_on.toordinal()),
        close_reason=None,
    )


def run_paper_book(
    entries: list[PaperEntry],
    sessions: list[tuple[date, dict[str, float]]],
) -> PaperBookStats:
    """Replay a paper opportunity book over a shadow window and emit statistics.

    ``sessions`` is an ordered list of ``(date, metrics)`` observations shared by
    every thesis (the sentinel resolves each thesis's probe from ``metrics``).
    The result is fully determined by the inputs — no wall clock, no order flow.
    """

    ordered_sessions = sorted(sessions, key=lambda s: s[0])
    results = [_track_one(entry, ordered_sessions) for entry in entries]

    entered = len(results)
    invalidated = sum(1 for r in results if r.outcome == "invalidated")
    expired = sum(1 for r in results if r.outcome == "expired")
    still_open = sum(1 for r in results if r.outcome == "open")
    closed = [r for r in results if r.outcome != "open"]
    mean_holding = (
        sum(r.holding_days for r in closed) / len(closed) if closed else 0.0
    )

    return PaperBookStats(
        entered=entered,
        invalidated=invalidated,
        expired=expired,
        still_open=still_open,
        invalidation_rate=(invalidated / entered) if entered else 0.0,
        mean_holding_days=mean_holding,
        results=results,
    )
