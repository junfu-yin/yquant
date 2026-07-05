from decimal import Decimal

from yquant.backtest.costs import (
    TaxConfig,
    hk_trade_cost,
    trade_cost,
    us_trade_cost,
)


def test_us_buy_has_no_sec_or_taf() -> None:
    cost = us_trade_cost("buy", Decimal("100"), Decimal("200"))
    assert cost.regulatory_fees == Decimal("0")
    assert cost.stamp_duty == Decimal("0")
    # Only slippage on a zero-commission buy.
    assert cost.slippage == Decimal("100") * Decimal("200") * Decimal("0.0005")
    assert cost.tax == Decimal("0")


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


def test_hk_stamp_duty_both_sides_rounded_up() -> None:
    buy = hk_trade_cost("buy", Decimal("100"), Decimal("350"))
    sell = hk_trade_cost("sell", Decimal("100"), Decimal("350"))
    # notional 35000 * 0.001 = 35 exactly → 35 HKD both sides.
    assert buy.stamp_duty == Decimal("35")
    assert sell.stamp_duty == Decimal("35")


def test_hk_stamp_duty_rounds_up_fractional() -> None:
    cost = hk_trade_cost("buy", Decimal("100"), Decimal("355"))
    # 35500 * 0.001 = 35.5 → rounded up to 36.
    assert cost.stamp_duty == Decimal("36")


def test_tax_hooks_default_zero_but_overridable() -> None:
    default = us_trade_cost("sell", Decimal("100"), Decimal("200"))
    assert default.tax == Decimal("0")

    taxed = us_trade_cost(
        "sell",
        Decimal("100"),
        Decimal("200"),
        tax=TaxConfig(capital_gains_rate=Decimal("0.10")),
    )
    assert taxed.tax == Decimal("20000") * Decimal("0.10")


def test_trade_cost_dispatches_by_market() -> None:
    us = trade_cost("us", "sell", Decimal("10"), Decimal("100"))
    hk = trade_cost("hk", "buy", Decimal("100"), Decimal("100"))
    assert us.stamp_duty == Decimal("0")
    assert hk.stamp_duty > Decimal("0")


def test_cost_breakdown_total_sums_components() -> None:
    cost = hk_trade_cost("sell", Decimal("100"), Decimal("350"))
    assert cost.total == (
        cost.commission + cost.slippage + cost.stamp_duty + cost.regulatory_fees + cost.tax
    )
