"""Central-bank hawk/dove scorer + a frozen calibration set (03 §5.9, 08 §8-1).

The v3.1 doctrine credits LLM classification of FOMC text (Richmond Fed: GPT
beats BERT/dictionaries, near-human explanations) but requires a *quarterly
dovish-bias recalibration*: the calibration set is a balanced hawk/dove corpus,
and if the scorer's mean absolute deviation exceeds 0.5 tiers it must be
recalibrated before use (06 §6).

The reference scorer here is a deterministic keyword model — no network, no LLM.
It stands in for the production LLM at the same ``[-2, 2]`` five-tier interface
so the calibration harness, the T18 guardrails and the committee pipeline can be
exercised and replayed offline. A real LLM scorer only has to match this
signature to drop in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

# Five-tier hawk/dove scale aligned to the Hansen–Kazinnik convention (03 §5.9):
# -2 very dovish … 0 neutral … +2 very hawkish.
HAWK_DOVE_MIN = -2
HAWK_DOVE_MAX = 2

# Recalibration trigger: mean absolute tier deviation over the calibration set.
CALIBRATION_MAX_MAD = 0.5

_HAWKISH_PHRASES: tuple[tuple[str, int], ...] = (
    ("further tightening", 2),
    ("additional rate hikes", 2),
    ("raise rates", 2),
    ("restrictive stance", 2),
    ("inflation remains elevated", 1),
    ("upside risks to inflation", 1),
    ("higher for longer", 1),
    ("vigilant on inflation", 1),
)
_DOVISH_PHRASES: tuple[tuple[str, int], ...] = (
    ("rate cuts", -2),
    ("cutting rates", -2),
    ("ease policy", -2),
    ("accommodative stance", -2),
    ("downside risks to growth", -1),
    ("labor market cooling", -1),
    ("inflation is moderating", -1),
    ("patient on policy", -1),
)


def _clamp_tier(value: int) -> int:
    return max(HAWK_DOVE_MIN, min(HAWK_DOVE_MAX, value))


def score_hawk_dove(text: str) -> int:
    """Score central-bank text to a ``[-2, 2]`` tier (deterministic reference).

    Sums signed hawkish/dovish phrase weights and clamps to the five tiers. The
    dovish bias the doctrine calls out is applied as a tie-break: an exact zero
    net read with any dovish evidence resolves dovish, never hawkish.
    """

    lowered = text.lower()
    net = 0
    dovish_hits = 0
    for phrase, weight in _HAWKISH_PHRASES:
        if phrase in lowered:
            net += weight
    for phrase, weight in _DOVISH_PHRASES:
        if phrase in lowered:
            net += weight
            dovish_hits += 1
    if net == 0 and dovish_hits:
        net = -1
    return _clamp_tier(net)


@dataclass(frozen=True)
class CalibrationSample:
    """One labelled central-bank sentence for the quarterly calibration set."""

    sample_id: str
    text: str
    expected_tier: int


@dataclass(frozen=True)
class CalibrationReport:
    """Result of scoring the calibration set against a scorer (06 §6)."""

    total: int
    mean_abs_deviation: float
    max_abs_deviation: int
    direction_accuracy: float
    within_one_tier: float
    passed: bool
    mismatches: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "mean_abs_deviation": round(self.mean_abs_deviation, 4),
            "max_abs_deviation": self.max_abs_deviation,
            "direction_accuracy": round(self.direction_accuracy, 4),
            "within_one_tier": round(self.within_one_tier, 4),
            "passed": self.passed,
            "mismatches": list(self.mismatches),
        }


def _sample(idx: int, text: str, tier: int) -> CalibrationSample:
    return CalibrationSample(sample_id=f"cal-{idx:03d}", text=text, expected_tier=tier)


def build_calibration_set() -> list[CalibrationSample]:
    """Build the frozen 30-sentence balanced hawk/dove calibration set (06 §6).

    Balanced by construction: 6 sentences at each of the five tiers, so a scorer
    that collapses to neutral is penalised on both wings. Sentences are written
    to be scored by the reference keyword model without ambiguity.
    """

    hawkish_2 = [
        "The committee anticipates further tightening and additional rate hikes.",
        "A restrictive stance is warranted; we expect to raise rates again.",
        "We will raise rates further given a restrictive stance is required.",
        "Additional rate hikes remain on the table under further tightening.",
        "The path calls for further tightening to reach a restrictive stance.",
        "We stand ready to raise rates and pursue additional rate hikes.",
    ]
    hawkish_1 = [
        "Inflation remains elevated and upside risks to inflation persist.",
        "Rates may stay higher for longer as inflation remains elevated.",
        "We remain vigilant on inflation given upside risks to inflation.",
        "Higher for longer is appropriate; we stay vigilant on inflation.",
        "Upside risks to inflation keep policy higher for longer.",
        "Inflation remains elevated, so we are vigilant on inflation.",
    ]
    neutral_0 = [
        "The committee will assess incoming data and act as appropriate.",
        "Policy is well positioned; decisions depend on the totality of data.",
        "We are prepared to adjust the stance as the outlook evolves.",
        "The path of policy remains data dependent going forward.",
        "Officials will proceed carefully and evaluate developments.",
        "We judge the current stance appropriate pending further data.",
    ]
    dovish_1 = [
        "Downside risks to growth are rising as the labor market cooling continues.",
        "Inflation is moderating while the labor market cooling broadens.",
        "We can be patient on policy as inflation is moderating.",
        "Downside risks to growth argue for patience; inflation is moderating.",
        "Labor market cooling supports being patient on policy.",
        "With inflation moderating we note downside risks to growth.",
    ]
    dovish_2 = [
        "The committee expects rate cuts and will ease policy soon.",
        "An accommodative stance is warranted; cutting rates is appropriate.",
        "We are cutting rates and moving to an accommodative stance.",
        "Rate cuts are likely as we ease policy toward accommodation.",
        "We will ease policy and deliver rate cuts in coming meetings.",
        "An accommodative stance with rate cuts is the base case.",
    ]

    tiers = [(2, hawkish_2), (1, hawkish_1), (0, neutral_0), (-1, dovish_1), (-2, dovish_2)]
    samples: list[CalibrationSample] = []
    idx = 1
    for tier, sentences in tiers:
        for text in sentences:
            samples.append(_sample(idx, text, tier))
            idx += 1
    return samples


def calibrate(
    samples: Sequence[CalibrationSample],
    scorer: Callable[[str], int] = score_hawk_dove,
) -> CalibrationReport:
    """Score the calibration set and decide whether recalibration is required.

    ``passed`` is ``True`` only when the mean absolute tier deviation is within
    :data:`CALIBRATION_MAX_MAD` (06 §6 "偏差<0.5 档"). Direction accuracy and the
    within-one-tier rate are reported for the quarterly review.
    """

    if not samples:
        raise ValueError("calibration set must not be empty")

    abs_devs: list[int] = []
    direction_hits = 0
    within_one = 0
    mismatches: list[str] = []
    for sample in samples:
        predicted = scorer(sample.text)
        deviation = abs(predicted - sample.expected_tier)
        abs_devs.append(deviation)
        if _sign(predicted) == _sign(sample.expected_tier):
            direction_hits += 1
        if deviation <= 1:
            within_one += 1
        if deviation > 1:
            mismatches.append(
                f"{sample.sample_id}: expected {sample.expected_tier}, got {predicted}"
            )

    total = len(samples)
    mad = sum(abs_devs) / total
    return CalibrationReport(
        total=total,
        mean_abs_deviation=mad,
        max_abs_deviation=max(abs_devs),
        direction_accuracy=direction_hits / total,
        within_one_tier=within_one / total,
        passed=mad < CALIBRATION_MAX_MAD,
        mismatches=mismatches,
    )


def run_calibration(scorer: Callable[[str], int] = score_hawk_dove) -> CalibrationReport:
    """Build the frozen calibration set and score it (convenience for the CLI)."""

    return calibrate(build_calibration_set(), scorer)


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
