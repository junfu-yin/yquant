from datetime import date
from decimal import Decimal

import pytest

from yquant.datasrc.market_rules import (
    US_CIRCUIT_BREAKER_LEVELS,
    market_rules,
)


def test_us_settlement_is_t2_before_2024_05_28() -> None:
    rules = market_rules("AAPL", "us", date(2023, 6, 1))

    assert rules.market == "us"
    assert rules.settlement_days == 2
    assert rules.reason == "us_t2_settlement"


def test_us_settlement_is_t1_from_2024_05_28() -> None:
    rules = market_rules("AAPL", "us", date(2024, 6, 1))

    assert rules.settlement_days == 1
    assert rules.reason == "us_t1_settlement"


def test_us_has_circuit_breakers_and_pdt_but_no_fixed_band() -> None:
    rules = market_rules("TSLA", "nasdaq", date(2024, 6, 1))

    assert rules.allows_intraday is True
    assert rules.circuit_breaker_levels == US_CIRCUIT_BREAKER_LEVELS
    assert rules.volatility_band_pct is None
    assert rules.pdt is not None
    assert rules.pdt.max_day_trades == 3


def test_pdt_active_only_below_equity_threshold() -> None:
    pdt = market_rules("AAPL", "us", date(2024, 6, 1)).pdt
    assert pdt is not None

    assert pdt.is_active(Decimal("10000")) is True
    assert pdt.is_active(Decimal("25000")) is False


def test_unsupported_market_raises() -> None:
    with pytest.raises(ValueError, match="v3.1a expected 'us'"):
        market_rules("0700.HK", "hk", date(2024, 6, 1))
