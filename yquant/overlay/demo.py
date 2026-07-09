"""A deterministic paper-book demo scenario (WP16, `yquant overlay paper-book`).

Mirrors the other module demos (``ui.demo`` / ``governance.demo``): a fixed,
LLM-free set of committee opportunities replayed over a short synthetic shadow
window so the CLI can prove the harness end-to-end and emit statistics without a
network, a wall clock, or a data repo. Every input is frozen here so the output
digest is reproducible (07).
"""

from __future__ import annotations

from datetime import date

from yquant.macro.schemas import OpportunityBookEntry
from yquant.overlay.paper_book import PaperBookStats, PaperEntry, run_paper_book


def _entry(
    *,
    ticker: str,
    thesis: str,
    invalidation: str,
    time_limit_days: int,
) -> OpportunityBookEntry:
    return OpportunityBookEntry(
        thesis=thesis,
        global_rationale="a global driver with a clear transmission channel to the US",
        us_ticker=ticker,
        direction="long",
        entry_condition=f"{ticker} reclaims its 50dma",
        invalidation_condition=invalidation,
        weight=0.03,
        time_limit_days=time_limit_days,
        red_team_note="crowded; size small and honour the time limit",
    )


def build_demo_paper_book() -> PaperBookStats:
    """Replay three frozen opportunities over a synthetic six-session window.

    One thesis is invalidated (S1), one hits its time limit (S3), one stays open
    to the window's end — enough to exercise every outcome path and the summary
    statistics the shadow gate reports.
    """

    entered_on = date(2024, 1, 2)
    entries = [
        PaperEntry(
            entry=_entry(
                ticker="MCHI",
                thesis="China policy-easing tactical long",
                invalidation="MCHI closes below 45",
                time_limit_days=90,
            ),
            entered_on=entered_on,
        ),
        PaperEntry(
            entry=_entry(
                ticker="INDA",
                thesis="India capex-cycle tactical long",
                invalidation="INDA closes below 40",
                time_limit_days=5,
            ),
            entered_on=entered_on,
        ),
        PaperEntry(
            entry=_entry(
                ticker="EWJ",
                thesis="Japan governance-reform tactical long",
                invalidation="EWJ closes below 55",
                time_limit_days=365,
            ),
            entered_on=entered_on,
        ),
    ]
    sessions: list[tuple[date, dict[str, float]]] = [
        (date(2024, 1, 2), {"MCHI": 50.0, "INDA": 50.0, "EWJ": 62.0}),
        (date(2024, 1, 3), {"MCHI": 48.0, "INDA": 49.0, "EWJ": 63.0}),
        (date(2024, 1, 4), {"MCHI": 44.0, "INDA": 48.0, "EWJ": 64.0}),  # MCHI invalidated
        (date(2024, 1, 5), {"MCHI": 43.0, "INDA": 47.0, "EWJ": 65.0}),
        (date(2024, 1, 8), {"MCHI": 42.0, "INDA": 46.0, "EWJ": 66.0}),  # INDA time limit
        (date(2024, 1, 9), {"MCHI": 41.0, "INDA": 45.0, "EWJ": 67.0}),
    ]
    return run_paper_book(entries, sessions)
