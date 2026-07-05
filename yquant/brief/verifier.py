"""Numeric verification helpers for LLM event cards."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

NUMBER_RE = re.compile(
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<unit>亿|万|千|百|%|％)?"
)

UNIT_MULTIPLIERS = {
    "亿": Decimal("100000000"),
    "万": Decimal("10000"),
    "千": Decimal("1000"),
    "百": Decimal("100"),
    "%": Decimal("0.01"),
    "％": Decimal("0.01"),
}


def normalize_number_token(token: str) -> Decimal | None:
    """Normalize a single numeric token into a Decimal comparable value."""

    match = NUMBER_RE.search(token.strip())
    if not match:
        return None

    raw_number = match.group("number").replace(",", "")
    unit = match.group("unit")
    try:
        value = Decimal(raw_number)
    except InvalidOperation:
        return None

    if unit:
        value *= UNIT_MULTIPLIERS[unit]
    return value


def extract_normalized_numbers(text: str) -> list[Decimal]:
    """Extract normalized Arabic-number tokens from source text."""

    values: list[Decimal] = []
    for match in NUMBER_RE.finditer(text):
        normalized = normalize_number_token(match.group(0))
        if normalized is not None:
            values.append(normalized)
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


def _close_enough(left: Decimal, right: Decimal, relative_tolerance: Decimal) -> bool:
    if left == right:
        return True
    denominator = max(abs(left), abs(right), Decimal("1"))
    return abs(left - right) / denominator <= relative_tolerance

