"""Numeric verification helpers for LLM event cards.

The main market is US (English filings), with HK as secondary. Source numbers
therefore appear in English forms: ``$1.2B`` / ``1,200 million`` / ``10,000,000``
/ ``10.00%`` / ``(1,234)`` (parenthesised negative) / ``US$3.5M``. Verification
normalises both the claimed number and every candidate in the source text to a
common magnitude, then compares within a tolerance. Only a claimed number that
still cannot be matched after normalisation is treated as fabricated.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Magnitude multipliers for English units, both letter and word forms.
UNIT_MULTIPLIERS = {
    "k": Decimal("1000"),
    "m": Decimal("1000000"),
    "b": Decimal("1000000000"),
    "t": Decimal("1000000000000"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
    "mn": Decimal("1000000"),
    "bn": Decimal("1000000000"),
}

# Currency symbols/prefixes stripped before parsing (US$, HK$, $, £, €, ¥).
_CURRENCY_RE = re.compile(r"(?:US|HK|C|A|S|NT)?\$|[£€¥]")

# A numeric token: optional parenthesis (negative), digits with optional
# thousands separators and decimals, optional magnitude unit, optional percent.
NUMBER_RE = re.compile(
    r"""
    (?P<open>\()?
    (?P<sign>[+-])?
    (?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    \s*
    (?P<unit>(?:trillion|billion|million|thousand|bn|mn|[kmbt])(?![A-Za-z]))?
    \s*
    (?P<percent>%|％)?
    (?P<close>\))?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize_number_token(token: str) -> Decimal | None:
    """Normalize a single numeric token into a comparable Decimal value."""

    cleaned = _CURRENCY_RE.sub("", token.strip())
    match = NUMBER_RE.search(cleaned)
    if not match:
        return None
    return _value_from_match(match)


def extract_normalized_numbers(text: str) -> list[Decimal]:
    """Extract normalized numeric tokens from source text."""

    cleaned = _CURRENCY_RE.sub("", text)
    values: list[Decimal] = []
    for match in NUMBER_RE.finditer(cleaned):
        value = _value_from_match(match)
        if value is not None:
            values.append(value)
    return values


def number_is_verified(
    claimed: str,
    source_text: str,
    *,
    relative_tolerance: Decimal = Decimal("0.000001"),
) -> bool:
    """Return whether a claimed number can be found in source text after normalization."""

    claimed_value = normalize_number_token(claimed)
    if claimed_value is None:
        return False

    for candidate in extract_normalized_numbers(source_text):
        if _close_enough(claimed_value, candidate, relative_tolerance):
            return True
    return False


def verify_key_numbers(key_numbers: list[str], source_text: str) -> dict[str, bool]:
    """Verify every key number against source text."""

    return {value: number_is_verified(value, source_text) for value in key_numbers}


def _value_from_match(match: re.Match[str]) -> Decimal | None:
    raw_number = match.group("number").replace(",", "")
    try:
        value = Decimal(raw_number)
    except InvalidOperation:
        return None

    unit = match.group("unit")
    if unit:
        value *= UNIT_MULTIPLIERS[unit.lower()]

    if match.group("percent"):
        value *= Decimal("0.01")

    # Parenthesised value or explicit minus sign means negative.
    is_negative = (match.group("open") and match.group("close")) or match.group("sign") == "-"
    if is_negative:
        value = -value
    return value


def _close_enough(left: Decimal, right: Decimal, relative_tolerance: Decimal) -> bool:
    if left == right:
        return True
    denominator = max(abs(left), abs(right), Decimal("1"))
    return abs(left - right) / denominator <= relative_tolerance
