"""Thesis-sentinel recall harness — a non-trading provider eval line (09 §2 ◆).

The Thesis sentinel is registered and evaluated like any provider, but it does
not hold budget. Its acceptance line is a *recall* target on a constructed set
of "thesis is dead" cases: a missed exit (false negative) is fatal, a spurious
exit (false positive) is merely annoying, so the doctrine sets recall ≥ 90% on
the dead-thesis set (09 §2 ◆). This harness builds a frozen labelled set — each
row is an opportunity plus a metrics snapshot and whether the invalidation truly
fired — and scores the sentinel's machine-readable evaluation against it.

The evaluator is the same single-comparator logic the UI sentinel uses, imported
from :mod:`yquant.ui.viewmodels`, so the recall number the panel shows is the
number the cockpit will actually deliver.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from yquant.macro.schemas import OpportunityBookEntry
from yquant.ui.viewmodels import evaluate_thesis

# Doctrine target: recall on the dead-thesis set (09 §2 ◆).
RECALL_TARGET = 0.90


@dataclass(frozen=True)
class ThesisRecallSample:
    """One labelled sentinel case: an entry, a metrics snapshot, the truth."""

    sample_id: str
    entry: OpportunityBookEntry
    metrics: dict[str, float]
    truly_dead: bool  # ground truth: has the invalidation condition really fired?


@dataclass(frozen=True)
class ThesisRecallReport:
    """Recall / precision of the sentinel over the dead-thesis set (09 §2 ◆)."""

    total: int
    dead_total: int
    true_positive: int
    false_negative: int
    false_positive: int
    recall: float
    precision: float
    passed: bool
    missed_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "dead_total": self.dead_total,
            "true_positive": self.true_positive,
            "false_negative": self.false_negative,
            "false_positive": self.false_positive,
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "recall_target": RECALL_TARGET,
            "passed": self.passed,
            "missed_ids": list(self.missed_ids),
        }


def _entry(
    ticker: str,
    thesis: str,
    invalidation: str,
    *,
    direction: str = "long",
) -> OpportunityBookEntry:
    return OpportunityBookEntry(
        thesis=thesis,
        global_rationale="frozen sentinel recall fixture",
        us_ticker=ticker,
        direction="long" if direction == "long" else "defensive",
        entry_condition="pullback to support",
        invalidation_condition=invalidation,
        weight=0.05,
        time_limit_days=45,
        red_team_note="constructed case; not a live recommendation",
    )


def build_thesis_recall_set() -> list[ThesisRecallSample]:
    """Build the frozen labelled dead-thesis set (10 dead + 6 alive).

    Dead cases put the metric on the wrong side of the machine-readable
    threshold; alive cases keep it on the right side or omit the metric so the
    sentinel must abstain (treated as alive — never a phantom exit).
    """

    dead: list[tuple[str, str, str, dict[str, float]]] = [
        ("SMH", "AI capex thesis", "SMH < 210", {"SMH": 205.0}),
        ("XLE", "energy supply squeeze", "XLE <= 80", {"XLE": 79.5}),
        ("GLD", "gold breakout", "GLD < 180", {"GLD": 175.0}),
        ("TLT", "duration trade", "TLT <= 90", {"TLT": 88.0}),
        ("QQQ", "megacap momentum", "QQQ < 400", {"QQQ": 395.0}),
        ("IWM", "small-cap catch-up", "IWM <= 190", {"IWM": 188.0}),
        ("XLF", "bank re-rating", "XLF < 34", {"XLF": 33.0}),
        ("XBI", "biotech M&A", "XBI <= 85", {"XBI": 84.0}),
        ("SPY", "index trend", "SPY < 420", {"SPY": 410.0}),
        ("SMH", "semis capex 2", "SMH <= 200", {"SMH": 199.0}),
    ]
    alive: list[tuple[str, str, str, dict[str, float]]] = [
        ("SMH", "AI capex thesis alive", "SMH < 210", {"SMH": 230.0}),
        ("XLE", "energy alive", "XLE <= 80", {"XLE": 92.0}),
        ("GLD", "gold alive", "GLD < 180", {"GLD": 195.0}),
        # Missing metric -> sentinel must abstain -> treated as alive.
        ("TLT", "duration alive (no data)", "TLT <= 90", {}),
        ("QQQ", "megacap alive", "QQQ < 400", {"QQQ": 440.0}),
        ("XLF", "bank alive", "XLF < 34", {"XLF": 38.0}),
    ]

    samples: list[ThesisRecallSample] = []
    idx = 0
    for ticker, thesis, invalidation, metrics in dead:
        samples.append(
            ThesisRecallSample(
                sample_id=f"dead-{idx:03d}",
                entry=_entry(ticker, thesis, invalidation),
                metrics=dict(metrics),
                truly_dead=True,
            )
        )
        idx += 1
    for ticker, thesis, invalidation, metrics in alive:
        samples.append(
            ThesisRecallSample(
                sample_id=f"alive-{idx:03d}",
                entry=_entry(ticker, thesis, invalidation),
                metrics=dict(metrics),
                truly_dead=False,
            )
        )
        idx += 1
    return samples


def evaluate_thesis_recall(samples: Sequence[ThesisRecallSample]) -> ThesisRecallReport:
    """Score the sentinel over the labelled set; recall gates admission (09 §2 ◆)."""

    if not samples:
        raise ValueError("recall set must not be empty")

    tp = fn = fp = 0
    missed: list[str] = []
    for sample in samples:
        row = evaluate_thesis(sample.entry, sample.metrics)
        fired = row.verdict == "invalidated"
        if sample.truly_dead:
            if fired:
                tp += 1
            else:
                fn += 1
                missed.append(sample.sample_id)
        elif fired:
            fp += 1

    dead_total = tp + fn
    recall = tp / dead_total if dead_total else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    return ThesisRecallReport(
        total=len(samples),
        dead_total=dead_total,
        true_positive=tp,
        false_negative=fn,
        false_positive=fp,
        recall=recall,
        precision=precision,
        passed=recall >= RECALL_TARGET,
        missed_ids=tuple(missed),
    )


def run_thesis_recall() -> ThesisRecallReport:
    """Build the frozen set and score it (WP10 non-trading provider eval line)."""

    return evaluate_thesis_recall(build_thesis_recall_set())


__all__ = [
    "RECALL_TARGET",
    "ThesisRecallReport",
    "ThesisRecallSample",
    "build_thesis_recall_set",
    "evaluate_thesis_recall",
    "run_thesis_recall",
]
