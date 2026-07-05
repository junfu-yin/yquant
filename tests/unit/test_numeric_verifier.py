from decimal import Decimal

from yquant.brief.verifier import (
    extract_normalized_numbers,
    normalize_number_token,
    number_is_verified,
    verify_key_numbers,
)


def test_normalize_chinese_units() -> None:
    assert normalize_number_token("1,000万") == Decimal("10000000")
    assert normalize_number_token("0.1亿") == Decimal("10000000")
    assert normalize_number_token("10.00%") == Decimal("0.1000")


def test_extract_normalized_numbers() -> None:
    values = extract_normalized_numbers("净利润1,000万，同比增长10.00%。")

    assert Decimal("10000000") in values
    assert Decimal("0.1000") in values


def test_number_is_verified_across_equivalent_units() -> None:
    source = "公司预计归母净利润约0.1亿元，同比增长10.00%。"

    assert number_is_verified("1000万", source)
    assert number_is_verified("10%", source)
    assert not number_is_verified("2000万", source)


def test_verify_key_numbers() -> None:
    source = "本次质押股份数量为1,000万股，占总股本10%。"

    assert verify_key_numbers(["0.1亿", "10%", "30%"], source) == {
        "0.1亿": True,
        "10%": True,
        "30%": False,
    }

