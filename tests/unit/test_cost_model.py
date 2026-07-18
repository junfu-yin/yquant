from decimal import Decimal

import pytest

from yquant.backtest.costs import (
    UsCostModel,
    trade_cost,
    us_trade_cost,
)


def test_us_buy_has_no_sec_or_taf() -> None:
    cost = us_trade_cost("buy", Decimal("100"), Decimal("200"))
    assert cost.regulatory_fees == Decimal("0")
    assert cost.commission == Decimal("9.50")
    assert cost.slippage == Decimal("100") * Decimal("200") * Decimal("0.0005")


def test_single_stock_slippage_is_double_the_etf_tier() -> None:
    etf = us_trade_cost("buy", Decimal("100"), Decimal("200"), instrument="etf")
    single = us_trade_cost("buy", Decimal("100"), Decimal("200"), instrument="single_stock")
    assert single.slippage == etf.slippage * Decimal("2")
    assert single.slippage == Decimal("100") * Decimal("200") * Decimal("0.0010")


def test_cost_breakdown_scaled_multiplies_all_components() -> None:
    cost = us_trade_cost("sell", Decimal("100"), Decimal("200"))
    zero = cost.scaled(Decimal("0"))
    doubled = cost.scaled(Decimal("2"))
    assert zero.total == Decimal("0")
    assert doubled.total == cost.total * Decimal("2")


def test_us_sell_charges_sec_and_taf() -> None:
    cost = us_trade_cost("sell", Decimal("100"), Decimal("200"))
    notional = Decimal("20000")
    expected_sec = notional * Decimal("0.0000278")
    expected_taf = Decimal("0.000166") * Decimal("100")
    assert cost.regulatory_fees == expected_sec + expected_taf


def test_us_taf_is_capped() -> None:
    # 1,000,000 shares → TAF would be 166 but cap is 8.30.
    cost = us_trade_cost("sell", Decimal("1000000"), Decimal("10"))
    notional = Decimal("10000000")
    expected_sec = notional * Decimal("0.0000278")
    assert cost.regulatory_fees == expected_sec + Decimal("8.30")


def test_trade_cost_dispatches_us_market() -> None:
    us = trade_cost("us", "sell", Decimal("10"), Decimal("100"))
    assert us.commission == Decimal("9.50")


def test_trade_cost_rejects_inactive_markets() -> None:
    try:
        trade_cost("hk", "buy", Decimal("100"), Decimal("100"))
    except ValueError as exc:
        assert "only supports market='us'" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_cost_breakdown_total_sums_components() -> None:
    cost = us_trade_cost("sell", Decimal("100"), Decimal("350"))
    assert cost.total == cost.commission + cost.slippage + cost.regulatory_fees


def test_cost_model_rejects_non_finite_rate() -> None:
    with pytest.raises(ValueError, match="finite"):
        UsCostModel(slippage_rate_etf=Decimal("NaN"))


def test_trade_cost_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError, match="positive"):
        us_trade_cost("buy", Decimal("0"), Decimal("100"))
