from datetime import date
from decimal import Decimal

import pytest

from yquant.datasrc.limit_rule import limit_rule, price_limit_rule


def test_main_board_default_limit() -> None:
    assert limit_rule("600000", "main", date(2024, 1, 2), False, date(1999, 11, 10)) == Decimal(
        "0.10"
    )


def test_st_limit() -> None:
    assert limit_rule("600000", "main", date(2024, 1, 2), True, date(1999, 11, 10)) == Decimal(
        "0.05"
    )


def test_chinext_rule_changes_after_2020_08_24() -> None:
    assert limit_rule("300001", "chinext", date(2019, 1, 2), False, date(2010, 1, 1)) == Decimal(
        "0.10"
    )
    assert limit_rule("300001", "chinext", date(2021, 1, 4), False, date(2010, 1, 1)) == Decimal(
        "0.20"
    )


def test_registration_based_first_five_trading_days_have_no_limit() -> None:
    rule = price_limit_rule(
        "688001",
        "star",
        date(2024, 1, 2),
        is_st=False,
        list_date=date(2023, 12, 29),
        trading_days_since_listing=3,
    )

    assert rule.up_pct is None
    assert rule.down_pct is None


def test_main_board_ipo_day_is_asymmetric() -> None:
    rule = price_limit_rule(
        "001234",
        "main",
        date(2024, 1, 2),
        is_st=False,
        list_date=date(2024, 1, 2),
        trading_days_since_listing=1,
    )

    assert rule.up_pct == Decimal("0.44")
    assert rule.down_pct == Decimal("0.36")
    with pytest.raises(ValueError, match="asymmetric"):
        _ = rule.symmetric_pct

