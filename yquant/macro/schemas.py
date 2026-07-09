"""Schemas for the M9 macro radar Layer-2/3 outputs (03 §5.9, ADR-32/34).

Two families live here:

* :class:`MacroEventCard` — the Layer-2 macro event card an LLM *summarises* but
  never gets to score into an order. ``hawk_dove`` is a five-tier central-bank
  read; ``magnitude`` drives escalation (``>= 4`` pushes and may convene an
  ad-hoc committee).
* the Layer-3 committee artefacts — :class:`ThesisProposal` (a candidate
  opportunity an analyst authors), :class:`OpportunityBookEntry`,
  :class:`RiskDashboardItem`, :class:`CoreTiltSuggestion` and the assembled
  :class:`CommitteeOutput`.

Every schema is *strongly validated*: an opportunity without a machine-readable
invalidation condition (the v3.1 red line "失效条件必填") cannot be constructed,
so the deterministic guardrail layer never has to trust prose.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

MacroSourceType = Literal[
    "central_bank",
    "data_release",
    "geopolitical",
    "cross_market",
    "other",
]

# A thesis is long (add risk) or defensive (cut risk / hedge without inverse ETFs).
ThesisDirection = Literal["long", "defensive"]

# Tokens that make an invalidation condition machine-checkable (03 §5.9 red line).
_COMPARATORS = ("<=", ">=", "==", "<", ">")
_CROSS_KEYWORDS = ("crosses", "breaks", "above", "below", "reclaims", "loses")
_NUMBER_RE = re.compile(r"\d")


def is_machine_readable_condition(text: str) -> bool:
    """Whether a condition is machine-readable: a comparator/keyword + a number.

    The committee red line forbids theses whose invalidation cannot be evaluated
    by a rule (a Thesis sentinel must be able to fire), so "if things get worse"
    is rejected while "VIX > 30" or "SPY loses 200dma at 420" passes.
    """

    lowered = text.lower().strip()
    if not lowered or not _NUMBER_RE.search(lowered):
        return False
    if any(op in lowered for op in _COMPARATORS):
        return True
    return any(keyword in lowered for keyword in _CROSS_KEYWORDS)


class MacroEventCard(BaseModel):
    """A Layer-2 macro event card (03 §5.9). The LLM writes prose; rules score."""

    event_id: str = Field(min_length=1)
    as_of: date
    source_type: MacroSourceType
    headline: str = Field(min_length=1, max_length=120)
    hawk_dove: int = Field(ge=-2, le=2)
    channels: list[str] = Field(min_length=1)
    us_expression_map: dict[str, str] = Field(min_length=1)
    magnitude: int = Field(ge=1, le=5)
    half_life_days: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    evidence_urls: list[str] = Field(min_length=1)
    contrarian_note: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1)

    @field_validator("evidence_urls")
    @classmethod
    def _urls_must_be_http(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("evidence_urls must all be http(s) URLs")
        return values

    @property
    def should_escalate(self) -> bool:
        """severity>=4 pushes and can convene an ad-hoc committee (03 §5.9)."""

        return self.magnitude >= 4


class ThesisProposal(BaseModel):
    """A candidate opportunity an analyst authors before red-team + synthesis.

    In production the Layer-3 analyst step (an LLM) drafts these; the pipeline
    then validates and never lets a model emit an order (ADR-22). ``weight`` is
    the requested Overlay sleeve weight, capped later by the budgeter.
    """

    thesis: str = Field(min_length=1, max_length=100)
    global_rationale: str = Field(min_length=1)
    us_ticker: str = Field(min_length=1)
    direction: ThesisDirection
    entry_condition: str = Field(min_length=1)
    invalidation_condition: str = Field(min_length=1)
    weight: float = Field(gt=0, le=1)
    time_limit_days: int = Field(ge=1)
    author: str = Field(min_length=1)

    @field_validator("us_ticker")
    @classmethod
    def _upper_ticker(cls, value: str) -> str:
        return value.strip().upper()


class OpportunityBookEntry(BaseModel):
    """A committee-approved opportunity (03 §5.9 Layer3, 09 §9 opportunity_book)."""

    thesis: str = Field(min_length=1, max_length=100)
    global_rationale: str = Field(min_length=1)
    us_ticker: str = Field(min_length=1)
    direction: ThesisDirection
    entry_condition: str = Field(min_length=1)
    invalidation_condition: str = Field(min_length=1)
    weight: float = Field(gt=0, le=1)
    time_limit_days: int = Field(ge=1)
    red_team_note: str = Field(min_length=1)

    @field_validator("invalidation_condition")
    @classmethod
    def _invalidation_machine_readable(cls, value: str) -> str:
        if not is_machine_readable_condition(value):
            raise ValueError(
                "invalidation_condition must be machine-readable (03 §5.9 red line)"
            )
        return value


class RiskDashboardItem(BaseModel):
    """One Top-5 risk row: the risk, my exposure, and how to defend it."""

    rank: int = Field(ge=1)
    risk_name: str = Field(min_length=1)
    portfolio_exposure: float = Field(ge=0, le=1)
    defensive_expression: str = Field(min_length=1)


class CoreTiltSuggestion(BaseModel):
    """A core-layer tilt inside the ±10% relative band (03 §5.9)."""

    asset: str = Field(min_length=1)
    tilt: float = Field(ge=-0.10, le=0.10)
    rationale: str = Field(min_length=1)


class RejectedThesis(BaseModel):
    """A thesis the red team or budgeter refused, with the rule it broke."""

    thesis: str
    us_ticker: str
    rule: str
    detail: str = ""


class CommitteeOutput(BaseModel):
    """The assembled Layer-3 output (risk dashboard + opportunity book + tilts)."""

    as_of: date
    regime_state: str
    dashboard: list[RiskDashboardItem] = Field(default_factory=list)
    opportunity_book: list[OpportunityBookEntry] = Field(default_factory=list)
    core_tilts: list[CoreTiltSuggestion] = Field(default_factory=list)
    rejected: list[RejectedThesis] = Field(default_factory=list)
    prompt_version: str = Field(min_length=1)

    @property
    def total_overlay_weight(self) -> float:
        return sum(entry.weight for entry in self.opportunity_book)
