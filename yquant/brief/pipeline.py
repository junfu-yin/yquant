"""M4 event-card pipeline: filing -> classified card with a numeric hard gate.

The pipeline is the deterministic spine of the individual-stock brief (03 §5.4).
Its job is *not* to write prose — a later LLM step does that — but to enforce the
hallucination guards the plan makes non-negotiable:

* **classification is structural**: the 8-K item code (or the Form 4 transaction
  codes) decide category/severity/direction, never a model (ADR-21);
* **every claimed number is re-verified against the source text** after unit
  normalisation, and a card that cites an unfound number is *rejected*, not
  softened (P5 "未验数字漏杀=0", 03 §5.4);
* **the source link is mandatory** (already enforced by the EventCard schema).

Because the whole path is a pure function of its inputs, a card built here is
replayable and its provenance envelope (07) carries the prompt_version even when
no model ran, so the ledger shape is uniform across rule- and LLM-built cards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from yquant.brief.filings import (
    Direction,
    Form4Filing,
    ItemSpec,
    classify_8k,
    left_truncate,
)
from yquant.brief.schemas import EventCard
from yquant.brief.verifier import verify_key_numbers

# Default input budget for filing bodies (03 §5.4 "输入裁剪"); left-truncated.
DEFAULT_MAX_INPUT_CHARS = 8000


class NumericVerificationError(ValueError):
    """Raised when a card cites a number absent from its source (P5 hard gate)."""

    def __init__(self, unverified: list[str]) -> None:
        self.unverified = unverified
        super().__init__(f"unverified key numbers (P5): {unverified!r}")


@dataclass(frozen=True)
class EightKFiling:
    """A minimal 8-K record the pipeline consumes (fields EDGAR exposes)."""

    symbol: str
    item_codes: list[str]
    filed_at: date
    body: str
    source_url: str
    key_numbers: list[str]


def build_8k_card(
    filing: EightKFiling,
    *,
    prompt_version: str = "brief_v1",
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
) -> EventCard:
    """Turn an 8-K filing into a verified :class:`EventCard`.

    Classification comes straight from the item code; the one-liner is a
    deterministic template (no LLM). Every ``key_number`` must be found in the
    (left-truncated) body after normalisation or the card is rejected.
    """

    spec = classify_8k(filing.item_codes, body=filing.body)
    body, truncated = left_truncate(filing.body, max_input_chars)
    _enforce_numeric_gate(filing.key_numbers, body)

    one_line = _eight_k_one_line(filing.symbol, spec)
    return EventCard(
        symbol=filing.symbol,
        market="us",
        source_type="announcement",
        event_type=spec.event_type,
        severity=spec.severity,
        direction=spec.direction,
        one_line=one_line,
        key_numbers=list(filing.key_numbers),
        rationale=f"8-K item {spec.code} · {spec.label}",
        source_url=filing.source_url,
        input_truncated=truncated,
        prompt_version=prompt_version,
    )


def build_form4_card(
    filing: Form4Filing,
    *,
    prompt_version: str = "brief_v1",
) -> EventCard:
    """Turn a parsed Form 4 into a verified :class:`EventCard` (no LLM).

    Direction is the sign of net insider shares; severity scales with the gross
    transaction value. Key numbers (net shares, gross USD) are generated from the
    structured fields, so they verify against themselves by construction — the
    gate still runs to keep every card on one honest path.
    """

    net = filing.net_shares()
    gross = filing.gross_value()
    direction: Direction = "利多" if net > 0 else "利空" if net < 0 else "中性"
    severity = _insider_severity(gross)

    verb = "acquired" if net > 0 else "disposed" if net < 0 else "reported"
    one_line = f"{filing.insider_name or 'Insider'} {verb} {abs(net):,.0f} {filing.symbol} shares"
    key_numbers = [f"{abs(net):,.0f} shares", f"${gross:,.2f}"]
    source_text = " ".join(key_numbers)
    _enforce_numeric_gate(key_numbers, source_text)

    return EventCard(
        symbol=filing.symbol,
        market="us",
        source_type="announcement",
        event_type="内部人交易",
        severity=severity,
        direction=direction,
        one_line=one_line,
        key_numbers=key_numbers,
        rationale=(
            f"Form 4 · {filing.insider_title or 'insider'} net {net:+,.0f} sh "
            f"(gross ${gross:,.0f})"
        ),
        source_url=filing.source_url,
        input_truncated=False,
        prompt_version=prompt_version,
    )


def _enforce_numeric_gate(key_numbers: list[str], source_text: str) -> None:
    results = verify_key_numbers(key_numbers, source_text)
    unverified = [number for number, ok in results.items() if not ok]
    if unverified:
        raise NumericVerificationError(unverified)


def _eight_k_one_line(symbol: str, spec: ItemSpec) -> str:
    line = f"{symbol}: {spec.label} ({spec.event_type})"
    return line[:60]


def _insider_severity(gross_value: float) -> int:
    value = abs(gross_value)
    if value >= 10_000_000:
        return 5
    if value >= 1_000_000:
        return 4
    if value >= 100_000:
        return 3
    if value >= 10_000:
        return 2
    return 1


__all__ = [
    "DEFAULT_MAX_INPUT_CHARS",
    "EightKFiling",
    "NumericVerificationError",
    "build_8k_card",
    "build_form4_card",
]
