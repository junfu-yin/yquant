"""M2 cost model (03 §5.2): US/HK trading costs, slippage, and frozen tax hooks.

Trading costs and slippage are real drags and are always modelled (03 §2.0).
The ``tax_*`` hooks (dividend withholding, capital gains) exist but default to
zero — the committer froze tax modelling in v3 (ADR-27). Users may override the
tax rates in config to run at their own risk.

Default fee rates are placeholders pending WP0 AS-6 verification; they are kept
in one place so a single edit updates every consumer. Rates are per-side unless
noted. All values are in the trade's own currency (USD for US, HKD for HK).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

Side = Literal["buy", "sell"]
Market = Literal["us", "hk"]


@dataclass(frozen=True)
class UsCostModel:
    """US equity costs (AS-6). SEC fee + FINRA TAF apply on sells only."""

    commission_per_share: Decimal = Decimal("0")  # default zero-commission broker
    min_commission: Decimal = Decimal("0")
    sec_fee_rate: Decimal = Decimal("0.0000278")  # SEC §31 fee on sale proceeds
    finra_taf_per_share: Decimal = Decimal("0.000166")  # TAF on shares sold
    finra_taf_cap: Decimal = Decimal("8.30")  # per-trade TAF cap
    slippage_rate: Decimal = Decimal("0.0005")  # 0.05% of notional


@dataclass(frozen=True)
class HkCostModel:
    """HK equity costs (AS-6). Stamp duty is charged on both sides, rounded up."""

    stamp_duty_rate: Decimal = Decimal("0.001")  # 0.1% both sides, round up to HKD
    sfc_levy_rate: Decimal = Decimal("0.000027")
    frc_levy_rate: Decimal = Decimal("0.0000015")
    exchange_fee_rate: Decimal = Decimal("0.0000565")
    ccass_fee_rate: Decimal = Decimal("0.00002")
    ccass_min: Decimal = Decimal("2")
    ccass_max: Decimal = Decimal("100")
    commission_rate: Decimal = Decimal("0")
    min_commission: Decimal = Decimal("0")
    slippage_rate: Decimal = Decimal("0.001")  # 0.1% of notional


@dataclass(frozen=True)
class TaxConfig:
    """Frozen tax hooks (ADR-27); default zero. Override at your own risk."""

    withholding_rate: Decimal = Decimal("0")
    capital_gains_rate: Decimal = Decimal("0")


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised costs for one fill (all in the trade currency)."""

    commission: Decimal
    slippage: Decimal
    stamp_duty: Decimal
    regulatory_fees: Decimal
    tax: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.slippage + self.stamp_duty + self.regulatory_fees + self.tax


def us_trade_cost(
    side: Side,
    shares: Decimal,
    price: Decimal,
    model: UsCostModel | None = None,
    tax: TaxConfig | None = None,
) -> CostBreakdown:
    """US per-fill cost. SEC fee + FINRA TAF only on sells (03 §5.2)."""

    model = model or UsCostModel()
    tax = tax or TaxConfig()
    notional = shares * price

    commission = max(model.commission_per_share * shares, model.min_commission)
    slippage = notional * model.slippage_rate

    regulatory = Decimal("0")
    if side == "sell":
        regulatory += notional * model.sec_fee_rate
        taf = min(model.finra_taf_per_share * shares, model.finra_taf_cap)
        regulatory += taf

    # Capital gains hook applies to sale proceeds; zero by default (ADR-27).
    tax_amount = notional * tax.capital_gains_rate if side == "sell" else Decimal("0")

    return CostBreakdown(
        commission=commission,
        slippage=slippage,
        stamp_duty=Decimal("0"),  # US has no stamp duty
        regulatory_fees=regulatory,
        tax=tax_amount,
    )


def hk_trade_cost(
    side: Side,
    shares: Decimal,
    price: Decimal,
    model: HkCostModel | None = None,
    tax: TaxConfig | None = None,
) -> CostBreakdown:
    """HK per-fill cost. Stamp duty both sides, rounded up to whole HKD."""

    model = model or HkCostModel()
    tax = tax or TaxConfig()
    notional = shares * price

    commission = max(notional * model.commission_rate, model.min_commission)
    slippage = notional * model.slippage_rate
    stamp_duty = (notional * model.stamp_duty_rate).to_integral_value(rounding=ROUND_CEILING)

    ccass = min(max(notional * model.ccass_fee_rate, model.ccass_min), model.ccass_max)
    regulatory = (
        notional * model.sfc_levy_rate
        + notional * model.frc_levy_rate
        + notional * model.exchange_fee_rate
        + ccass
    )

    tax_amount = notional * tax.capital_gains_rate if side == "sell" else Decimal("0")

    return CostBreakdown(
        commission=commission,
        slippage=slippage,
        stamp_duty=stamp_duty,
        regulatory_fees=regulatory,
        tax=tax_amount,
    )


def trade_cost(
    market: Market,
    side: Side,
    shares: Decimal,
    price: Decimal,
    *,
    us_model: UsCostModel | None = None,
    hk_model: HkCostModel | None = None,
    tax: TaxConfig | None = None,
) -> CostBreakdown:
    """Dispatch to the per-market cost model."""

    if market == "us":
        return us_trade_cost(side, shares, price, us_model, tax)
    return hk_trade_cost(side, shares, price, hk_model, tax)
