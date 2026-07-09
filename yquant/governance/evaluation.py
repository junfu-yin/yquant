"""Offline evaluation with the J3 contamination split (09 §2, ADR-24).

An LLM / ML provider is only credited for samples *after* its declared
``knowledge_cutoff``. Everything at or before the cutoff is a leak of the
model's parametric memory into the "prediction" and is stamped ``contaminated``:
it may be shown for exploration but must never enter a pass/promote decision
(09 §2, one-of-the-first-class constraints). Rule providers (no cutoff) have no
contamination frontier — the whole window is a legitimate forward test.

The scorer here is any deterministic callable ``sample -> predicted``; the
harness compares against pre-labels and reports separate metrics for the clean
(post-cutoff) and contaminated (pre-cutoff) partitions so a reviewer can see the
inflation the leak would have produced.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from yquant.strategies.base import ModelCard


@dataclass(frozen=True)
class EvalSample:
    """One labelled evaluation observation for a provider.

    ``window_start`` is the date the sample's information belongs to; the J3 rule
    compares it against the provider's ``knowledge_cutoff``.
    """

    sample_id: str
    window_start: date
    predicted: float  # signed direction in [-1, 1] (or a class-mapped score)
    realized: float  # realised forward return sign/magnitude for scoring


@dataclass(frozen=True)
class PartitionMetrics:
    """Directional-accuracy metrics for one partition of the eval set."""

    count: int
    hit_rate: float  # fraction with matching sign of predicted vs realized
    mean_abs_error: float

    def as_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "hit_rate": round(self.hit_rate, 4),
            "mean_abs_error": round(self.mean_abs_error, 4),
        }


@dataclass(frozen=True)
class OfflineEvaluationReport:
    """J3-split offline evaluation of a provider (09 §2).

    ``credited`` is the post-cutoff (or all, for rule providers) partition that
    a promotion decision may use. ``contaminated`` is the pre-cutoff partition —
    present for transparency, forbidden as evidence. ``admissible`` mirrors the
    doctrine: a decision may only read ``credited``.
    """

    provider_id: str
    kind: str
    knowledge_cutoff: date | None
    credited: PartitionMetrics
    contaminated: PartitionMetrics
    contaminated_sample_ids: tuple[str, ...]

    @property
    def has_contamination(self) -> bool:
        return self.contaminated.count > 0

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind,
            "knowledge_cutoff": (
                self.knowledge_cutoff.isoformat() if self.knowledge_cutoff else None
            ),
            "credited": self.credited.as_dict(),
            "contaminated": self.contaminated.as_dict(),
            "has_contamination": self.has_contamination,
            "contaminated_sample_ids": list(self.contaminated_sample_ids),
            "note": (
                "contaminated samples are exploratory only; forbidden as promotion evidence"
            ),
        }


def split_on_cutoff(
    samples: Sequence[EvalSample],
    knowledge_cutoff: date | None,
) -> tuple[list[EvalSample], list[EvalSample]]:
    """Partition ``samples`` into (credited, contaminated) on the cutoff.

    A ``None`` cutoff (rule provider) credits everything. For LLM/ML providers a
    sample whose ``window_start`` is on or before the cutoff is contaminated
    (the model may have memorised that period), the strict-after remainder is
    credited (09 §2: "截止**之后**为有效前向样本").
    """

    if knowledge_cutoff is None:
        return list(samples), []
    credited = [s for s in samples if s.window_start > knowledge_cutoff]
    contaminated = [s for s in samples if s.window_start <= knowledge_cutoff]
    return credited, contaminated


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _score_partition(samples: Sequence[EvalSample]) -> PartitionMetrics:
    if not samples:
        return PartitionMetrics(count=0, hit_rate=0.0, mean_abs_error=0.0)
    hits = sum(1 for s in samples if _sign(s.predicted) == _sign(s.realized))
    abs_err = sum(abs(s.predicted - s.realized) for s in samples)
    n = len(samples)
    return PartitionMetrics(
        count=n,
        hit_rate=hits / n,
        mean_abs_error=abs_err / n,
    )


def evaluate_offline(
    card: ModelCard,
    samples: Sequence[EvalSample],
) -> OfflineEvaluationReport:
    """Run the J3-split offline evaluation for one provider (09 §2).

    The report separates credited vs contaminated metrics; the contaminated ids
    are surfaced so the UI can red-flag them. This function never *decides*
    admission — it produces the evidence the ladder (09 §6) reads.
    """

    credited_samples, contaminated_samples = split_on_cutoff(samples, card.knowledge_cutoff)
    return OfflineEvaluationReport(
        provider_id=card.provider_id,
        kind=card.kind,
        knowledge_cutoff=card.knowledge_cutoff,
        credited=_score_partition(credited_samples),
        contaminated=_score_partition(contaminated_samples),
        contaminated_sample_ids=tuple(s.sample_id for s in contaminated_samples),
    )


def build_scorer_report(
    card: ModelCard,
    labelled: Sequence[tuple[str, date, float]],
    scorer: Callable[[str, date], float],
) -> OfflineEvaluationReport:
    """Convenience: score ``(sample_id, window_start, realized)`` rows with ``scorer``.

    ``scorer`` maps ``(sample_id, window_start) -> predicted``; the realised
    outcome comes from the label. Keeps the J3 split identical to
    :func:`evaluate_offline`.
    """

    samples = [
        EvalSample(
            sample_id=sample_id,
            window_start=window_start,
            predicted=scorer(sample_id, window_start),
            realized=realized,
        )
        for sample_id, window_start, realized in labelled
    ]
    return evaluate_offline(card, samples)


__all__ = [
    "EvalSample",
    "OfflineEvaluationReport",
    "PartitionMetrics",
    "build_scorer_report",
    "evaluate_offline",
    "split_on_cutoff",
]
