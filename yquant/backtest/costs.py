"""M2 cost model (03 §5.2): US trading costs and slippage.

Trading costs and slippage are always modelled. Tax is explicitly out of scope
in v3.1a; do not add tax hooks to the active execution path. Defaults are
configurable placeholders pending WP0 AS-8 Selfwealth fee verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Side = Literal["buy", "sell"]
Market = Literal["us"]


@dataclass(frozen=True)
class UsCostModel:
    """US equity costs (AS-6). SEC fee + FINRA TAF apply on sells only."""

    commission_per_trade: Decimal = Decimal("9.50")  # Selfwealth default, verify in AS-8.
    sec_fee_rate: Decimal = Decimal("0.0000278")  # SEC §31 fee on sale proceeds
    finra_taf_per_share: Decimal = Decimal("0.000166")  # TAF on shares sold
    finra_taf_cap: Decimal = Decimal("8.30")  # per-trade TAF cap
    slippage_rate: Decimal = Decimal("0.0005")  # 0.05% of notional


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised costs for one US fill, all in USD."""

    commission: Decimal
    slippage: Decimal
    regulatory_fees: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.slippage + self.regulatory_fees


def us_trade_cost(
    side: Side,
    shares: Decimal,
    price: Decimal,
    model: UsCostModel | None = None,
) -> CostBreakdown:
    """US per-fill cost. SEC fee + FINRA TAF only on sells (03 §5.2)."""

    model = model or UsCostModel()
    notional = shares * price

    commission = model.commission_per_trade
    slippage = notional * model.slippage_rate

    regulatory = Decimal("0")
    if side == "sell":
        regulatory += notional * model.sec_fee_rate
        taf = min(model.finra_taf_per_share * shares, model.finra_taf_cap)
        regulatory += taf

    return CostBreakdown(
        commission=commission,
        slippage=slippage,
        regulatory_fees=regulatory,
    )


def trade_cost(
    market: str,
    side: Side,
    shares: Decimal,
    price: Decimal,
    *,
    us_model: UsCostModel | None = None,
) -> CostBreakdown:
    """Dispatch to the active v3.1a execution cost model."""

    if market.strip().lower() != "us":
        raise ValueError("v3.1a execution scope only supports market='us'")
    return us_trade_cost(side, shares, price, us_model)
