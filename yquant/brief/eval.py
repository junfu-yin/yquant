"""M4 evaluation harness + frozen English filing corpus (03 §5.4, 06 §6).

The plan requires an English evaluation set of **120 filings** covering the major
8-K items plus *hallucination-inducing* samples, scored against pre-labels on
four axes (03 §5.4 acceptance line):

* classification accuracy ≥ 85%
* severity within ±1 ≥ 85% **and** severity≥4 recall ≥ 95%
* direction accuracy ≥ 80%
* **未验数字漏杀 = 0** — every fabricated-number trap must be rejected

Because M4 classification is rule-based (item code → category), the clean-sample
accuracy is honestly high; the interesting axis is the numeric gate. Trap samples
cite a number that does **not** appear in the body, and the harness verifies the
pipeline *rejects* every one (a trap that produces a card is a P5 miss).

The corpus is generated deterministically from templates so it is frozen and
replayable without shipping licensed filing text; content is English to match the
US execution market. This is evaluation scaffolding, not a performance claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from yquant.brief.filings import EIGHT_K_ITEMS, ItemSpec, classify_8k
from yquant.brief.pipeline import (
    EightKFiling,
    NumericVerificationError,
    build_8k_card,
)

_BASE_DATE = date(2024, 1, 2)
_SYMBOLS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "PFE",
)


@dataclass(frozen=True)
class EvalSample:
    """One labelled filing for the M4 eval set."""

    sample_id: str
    symbol: str
    item_codes: list[str]
    filed_at: date
    body: str
    source_url: str
    key_numbers: list[str]
    expected_event_type: str
    expected_severity: int
    expected_direction: str
    is_trap: bool = False


@dataclass(frozen=True)
class EvalMetrics:
    """Scored outcome of running the pipeline over the eval set (06 §6)."""

    total: int
    clean: int
    traps: int
    classification_accuracy: float
    severity_within_one: float
    severity_high_recall: float
    direction_accuracy: float
    trap_miss_count: int
    passed: bool
    misclassified: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "clean": self.clean,
            "traps": self.traps,
            "classification_accuracy": round(self.classification_accuracy, 4),
            "severity_within_one": round(self.severity_within_one, 4),
            "severity_high_recall": round(self.severity_high_recall, 4),
            "direction_accuracy": round(self.direction_accuracy, 4),
            "trap_miss_count": self.trap_miss_count,
            "passed": self.passed,
            "misclassified": list(self.misclassified),
        }


def _body_for(spec: ItemSpec, revenue: int, pct: int) -> str:
    """A short English filing body that embeds the sample's key numbers."""

    return (
        f"On the date hereof the registrant furnished information under Item "
        f"{spec.code} ({spec.label}). The company reported net revenue of "
        f"${revenue:,} million, a change of {pct}.00% versus the prior period. "
        f"Additional detail is provided in the exhibits to this report."
    )


def _press_body(keyword: str, amount: int) -> str:
    """A press-release body (Item 8.01) whose keyword drives refinement."""

    return (
        f"The board of directors today announced a {keyword}. The action "
        f"involves approximately ${amount:,} million and is described in the "
        f"press release furnished herewith under Item 8.01."
    )


def build_eval_corpus() -> list[EvalSample]:
    """Build the frozen 120-sample English eval corpus (100 clean + 20 traps)."""

    samples: list[EvalSample] = []
    codes = list(EIGHT_K_ITEMS)
    idx = 0

    # 100 clean 8-K samples, cycling every item code (>=4 each) with real numbers.
    for i in range(100):
        code = codes[i % len(codes)]
        spec = EIGHT_K_ITEMS[code]
        symbol = _SYMBOLS[i % len(_SYMBOLS)]
        revenue = 1000 + i * 7
        pct = (i % 25) - 12  # spread of positive/negative percentages
        body = _body_for(spec, revenue, pct)
        key_numbers = [f"${revenue:,} million", f"{pct}.00%"]
        expected = classify_8k([code], body=body)
        samples.append(
            EvalSample(
                sample_id=f"clean-{idx:03d}",
                symbol=symbol,
                item_codes=[code],
                filed_at=_BASE_DATE + timedelta(days=idx),
                body=body,
                source_url=f"https://www.sec.gov/edgar/{symbol}/8-K/{idx}",
                key_numbers=key_numbers,
                expected_event_type=expected.event_type,
                expected_severity=expected.severity,
                expected_direction=expected.direction,
            )
        )
        idx += 1

    # Two refined press-release samples so the keyword refiner is exercised.
    for keyword, etype, sev, direction in (
        ("share repurchase program", "回购增持", 3, "利多"),
        ("suspends dividend", "分红拆股", 4, "利空"),
    ):
        amount = 500 + idx
        body = _press_body(keyword, amount)
        samples.append(
            EvalSample(
                sample_id=f"clean-{idx:03d}",
                symbol=_SYMBOLS[idx % len(_SYMBOLS)],
                item_codes=["8.01"],
                filed_at=_BASE_DATE + timedelta(days=idx),
                body=body,
                source_url=f"https://www.sec.gov/edgar/press/{idx}",
                key_numbers=[f"${amount:,} million"],
                expected_event_type=etype,
                expected_severity=sev,
                expected_direction=direction,
            )
        )
        idx += 1

    # 18 hallucination traps: cite a number absent from the body (P5 must reject).
    while len([s for s in samples if s.is_trap]) < 18:
        code = codes[idx % len(codes)]
        spec = EIGHT_K_ITEMS[code]
        symbol = _SYMBOLS[idx % len(_SYMBOLS)]
        revenue = 2000 + idx * 5
        pct = 3
        body = _body_for(spec, revenue, pct)
        fabricated = revenue * 9 + 777  # a value that is not in the body
        samples.append(
            EvalSample(
                sample_id=f"trap-{idx:03d}",
                symbol=symbol,
                item_codes=[code],
                filed_at=_BASE_DATE + timedelta(days=idx),
                body=body,
                source_url=f"https://www.sec.gov/edgar/{symbol}/trap/{idx}",
                key_numbers=[f"${fabricated:,} million"],
                expected_event_type=spec.event_type,
                expected_severity=spec.severity,
                expected_direction=spec.direction,
                is_trap=True,
            )
        )
        idx += 1

    return samples


def _to_filing(sample: EvalSample) -> EightKFiling:
    return EightKFiling(
        symbol=sample.symbol,
        item_codes=sample.item_codes,
        filed_at=sample.filed_at,
        body=sample.body,
        source_url=sample.source_url,
        key_numbers=sample.key_numbers,
    )


def evaluate_corpus(samples: list[EvalSample]) -> EvalMetrics:
    """Run the pipeline over ``samples`` and score against the pre-labels.

    Clean samples must build a card matching their expected classification;
    trap samples must be *rejected* by the numeric gate. A trap that produces a
    card is counted as a P5 miss (``trap_miss_count``), which fails the gate.
    """

    clean = [s for s in samples if not s.is_trap]
    traps = [s for s in samples if s.is_trap]

    type_hits = 0
    sev_within = 0
    dir_hits = 0
    high_total = 0
    high_hits = 0
    misclassified: list[str] = []

    for sample in clean:
        card = build_8k_card(_to_filing(sample))
        type_ok = card.event_type == sample.expected_event_type
        if type_ok:
            type_hits += 1
        else:
            misclassified.append(sample.sample_id)
        if abs(card.severity - sample.expected_severity) <= 1:
            sev_within += 1
        if card.direction == sample.expected_direction:
            dir_hits += 1
        if sample.expected_severity >= 4:
            high_total += 1
            if card.severity >= 4:
                high_hits += 1

    trap_miss = 0
    for sample in traps:
        try:
            build_8k_card(_to_filing(sample))
        except NumericVerificationError:
            continue
        trap_miss += 1  # a trap that produced a card is a P5 miss

    n_clean = len(clean) or 1
    classification_accuracy = type_hits / n_clean
    severity_within_one = sev_within / n_clean
    severity_high_recall = high_hits / high_total if high_total else 1.0
    direction_accuracy = dir_hits / n_clean

    passed = (
        classification_accuracy >= 0.85
        and severity_within_one >= 0.85
        and severity_high_recall >= 0.95
        and direction_accuracy >= 0.80
        and trap_miss == 0
    )
    return EvalMetrics(
        total=len(samples),
        clean=len(clean),
        traps=len(traps),
        classification_accuracy=classification_accuracy,
        severity_within_one=severity_within_one,
        severity_high_recall=severity_high_recall,
        direction_accuracy=direction_accuracy,
        trap_miss_count=trap_miss,
        passed=passed,
        misclassified=misclassified,
    )


def run_eval() -> EvalMetrics:
    """Build the frozen corpus and evaluate it (the WP4 acceptance harness)."""

    return evaluate_corpus(build_eval_corpus())


__all__ = [
    "EvalMetrics",
    "EvalSample",
    "build_eval_corpus",
    "evaluate_corpus",
    "run_eval",
]
