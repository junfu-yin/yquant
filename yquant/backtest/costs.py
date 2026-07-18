"""M2 cost model (03 §5.2): US trading costs and slippage.

Trading costs and slippage are always modelled. Tax is explicitly out of scope
in v3.1a; do not add tax hooks to the active execution path. Defaults are
configurable placeholders pending WP0 AS-8 Selfwealth fee verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

Side = Literal["buy", "sell"]
Market = Literal["us"]
Instrument = Literal["etf", "single_stock"]


@dataclass(frozen=True)
class UsCostModel:
    """US equity costs (AS-6). SEC fee + FINRA TAF apply on sells only.

    Slippage is tiered by instrument (03 §5.2): 0.05% of notional for ETFs,
    0.10% for single stocks. Callers pass the instrument kind per fill; the
    default is ``"etf"`` so the broad-index backtests read the tighter rate.
    """

    commission_per_trade: Decimal = Decimal("9.50")  # Selfwealth default, verify in AS-8.
    sec_fee_rate: Decimal = Decimal("0.0000278")  # SEC §31 fee on sale proceeds
    finra_taf_per_share: Decimal = Decimal("0.000166")  # TAF on shares sold
    finra_taf_cap: Decimal = Decimal("8.30")  # per-trade TAF cap
    slippage_rate_etf: Decimal = Decimal("0.0005")  # 0.05% of notional (ETF)
    slippage_rate_single: Decimal = Decimal("0.0010")  # 0.10% of notional (single stock)

    def __post_init__(self) -> None:
        for name, value in (
            ("commission_per_trade", self.commission_per_trade),
            ("sec_fee_rate", self.sec_fee_rate),
            ("finra_taf_per_share", self.finra_taf_per_share),
            ("finra_taf_cap", self.finra_taf_cap),
            ("slippage_rate_etf", self.slippage_rate_etf),
            ("slippage_rate_single", self.slippage_rate_single),
        ):
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    def slippage_rate_for(self, instrument: Instrument) -> Decimal:
        """Return the slippage rate for one instrument kind."""

        if instrument == "single_stock":
            return self.slippage_rate_single
        return self.slippage_rate_etf

    @classmethod
    def from_rates(
        cls,
        *,
        commission_per_trade: float,
        sec_fee_rate: float,
        finra_taf_per_share: float,
        finra_taf_cap: float,
        slippage_rate_etf: float,
        slippage_rate_single: float,
    ) -> UsCostModel:
        """Build a model from float config values (exact via ``Decimal(str(...))``)."""

        return cls(
            commission_per_trade=Decimal(str(commission_per_trade)),
            sec_fee_rate=Decimal(str(sec_fee_rate)),
            finra_taf_per_share=Decimal(str(finra_taf_per_share)),
            finra_taf_cap=Decimal(str(finra_taf_cap)),
            slippage_rate_etf=Decimal(str(slippage_rate_etf)),
            slippage_rate_single=Decimal(str(slippage_rate_single)),
        )


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised costs for one US fill, all in USD."""

    commission: Decimal
    slippage: Decimal
    regulatory_fees: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.slippage + self.regulatory_fees

    def scaled(self, multiplier: Decimal) -> CostBreakdown:
        """Return a copy with every component scaled (0/1x/2x cost report)."""

        return CostBreakdown(
            commission=self.commission * multiplier,
            slippage=self.slippage * multiplier,
            regulatory_fees=self.regulatory_fees * multiplier,
        )


def us_trade_cost(
    side: Side,
    shares: Decimal,
    price: Decimal,
    model: UsCostModel | None = None,
    *,
    instrument: Instrument = "etf",
) -> CostBreakdown:
    """US per-fill cost. SEC fee + FINRA TAF only on sells (03 §5.2).

    ``instrument`` selects the slippage tier (ETF 0.05% vs single-stock 0.10%).
    """

    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if instrument not in ("etf", "single_stock"):
        raise ValueError("instrument must be 'etf' or 'single_stock'")
    try:
        valid_inputs = shares.is_finite() and price.is_finite() and shares > 0 and price > 0
    except InvalidOperation as exc:
        raise ValueError("shares and price must be finite and positive") from exc
    if not valid_inputs:
        raise ValueError("shares and price must be finite and positive")

    model = model or UsCostModel()
    notional = shares * price

    commission = model.commission_per_trade
    slippage = notional * model.slippage_rate_for(instrument)

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
    instrument: Instrument = "etf",
) -> CostBreakdown:
    """Dispatch to the active v3.1a execution cost model."""

    if market.strip().lower() != "us":
        raise ValueError("v3.1a execution scope only supports market='us'")
    return us_trade_cost(side, shares, price, us_model, instrument=instrument)
