from decimal import Decimal

from yquant.brief.verifier import (
    extract_normalized_numbers,
    normalize_number_token,
    number_is_verified,
    verify_key_numbers,
)


def test_normalize_english_units() -> None:
    assert normalize_number_token("$1.2B") == Decimal("1200000000")
    assert normalize_number_token("1,200 million") == Decimal("1200000000")
    assert normalize_number_token("10,000,000") == Decimal("10000000")
    assert normalize_number_token("10.00%") == Decimal("0.1000")


def test_normalize_parenthesised_negative_and_currency() -> None:
    assert normalize_number_token("(1,234)") == Decimal("-1234")
    assert normalize_number_token("US$3.5M") == Decimal("3500000")
    assert normalize_number_token("-500K") == Decimal("-500000")


def test_extract_normalized_numbers() -> None:
    values = extract_normalized_numbers("Net income was $1,200 million, up 10.00% YoY.")

    assert Decimal("1200000000") in values
    assert Decimal("0.1000") in values


def test_number_is_verified_across_equivalent_units() -> None:
    source = "The company expects net income of about $1.2B, up 10.00% year over year."

    assert number_is_verified("1,200 million", source)
    assert number_is_verified("10%", source)
    assert not number_is_verified("2,000 million", source)


def test_verify_key_numbers() -> None:
    source = "Revenue reached $10,000,000, representing 10% of total sales."

    assert verify_key_numbers(["10M", "10%", "30%"], source) == {
        "10M": True,
        "10%": True,
        "30%": False,
    }
