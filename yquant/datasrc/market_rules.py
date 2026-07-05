"""US/HK market microstructure and settlement rules.

Neither US nor HK equities have A-share style daily price limits. What matters
for the backtest/broker layer is the settlement cycle, whether intraday trading
is allowed, the PDT constraint (US), and the volatility-control facts (US LULD /
market circuit breaker, HK VCM / closing-auction band).

`market_rules` is a pure function so the rest of the code gets a typed object
instead of scattering magic numbers. Effective dates and exact fee/rule values
are verified in WP0 AS-6; the trade calendar (and therefore actual settle dates)
is owned by M1, so this module only returns the settlement horizon `N`, not a
concrete settle date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

Market = Literal["us", "hk"]

# US moved from T+2 to T+1 settlement on 2024-05-28 (SEC rule 15c6-1).
US_T1_SETTLEMENT_START = date(2024, 5, 28)

# Market-level circuit breaker trigger levels: S&P 500 intraday decline.
US_CIRCUIT_BREAKER_LEVELS: tuple[Decimal, ...] = (
    Decimal("0.07"),
    Decimal("0.13"),
    Decimal("0.20"),
)

# HK Volatility Control Mechanism: ±10% deviation from reference price.
HK_VCM_BAND_PCT = Decimal("0.10")
# HK Closing Auction Session order band: ±5% of reference price.
HK_CAS_BAND_PCT = Decimal("0.05")


@dataclass(frozen=True)
class PdtRule:
    """US Pattern Day Trader constraint.

    Active only while account equity is below `equity_threshold`. Above it the
    limit does not apply, so callers must pass equity to `is_active`.
    """

    equity_threshold: Decimal
    max_day_trades: int
    window_trading_days: int

    def is_active(self, account_equity: Decimal) -> bool:
        return account_equity < self.equity_threshold


US_PDT_RULE = PdtRule(
    equity_threshold=Decimal("25000"),
    max_day_trades=3,
    window_trading_days=5,
)


@dataclass(frozen=True)
class MarketRuleSet:
    """Settlement and microstructure rules applicable to a symbol on a day.

    `volatility_band_pct` is `None` for US because LULD is tier-based rather than
    a single fixed percentage; the broker enforces it as "fill price must stay in
    that day's [low, high]" instead. For HK it is the VCM ±10% band.
    `closing_auction_band_pct` is the HK CAS ±5% band (US closing auctions have no
    fixed band). `circuit_breaker_levels` is empty for HK (no market-level halt).
    """

    market: Market
    settlement_days: int
    allows_intraday: bool
    circuit_breaker_levels: tuple[Decimal, ...]
    volatility_band_pct: Decimal | None
    closing_auction_band_pct: Decimal | None
    pdt: PdtRule | None
    reason: str


def market_rules(symbol: str, market: str, day: date) -> MarketRuleSet:
    """Return the settlement/microstructure rules for a symbol on a trading day.

    `settlement_days` is the T+N horizon only; converting it to an actual settle
    date requires the market trading calendar, which M1 owns.
    """

    del symbol  # Reserved for future symbol-level exceptions (e.g. ADR-listed HK names).
    normalized = _normalize_market(market)

    if normalized == "us":
        settlement = 1 if day >= US_T1_SETTLEMENT_START else 2
        return MarketRuleSet(
            market="us",
            settlement_days=settlement,
            allows_intraday=True,
            circuit_breaker_levels=US_CIRCUIT_BREAKER_LEVELS,
            volatility_band_pct=None,
            closing_auction_band_pct=None,
            pdt=US_PDT_RULE,
            reason=f"us_t{settlement}_settlement",
        )

    return MarketRuleSet(
        market="hk",
        settlement_days=2,
        allows_intraday=True,
        circuit_breaker_levels=(),
        volatility_band_pct=HK_VCM_BAND_PCT,
        closing_auction_band_pct=HK_CAS_BAND_PCT,
        pdt=None,
        reason="hk_t2_settlement",
    )


def _normalize_market(market: str) -> Market:
    value = market.strip().lower()
    aliases = {
        "us": "us",
        "usa": "us",
        "nyse": "us",
        "nasdaq": "us",
        "amex": "us",
        "hk": "hk",
        "hkex": "hk",
        "hkg": "hk",
        "sehk": "hk",
    }
    normalized = aliases.get(value, value)
    if normalized not in {"us", "hk"}:
        raise ValueError(f"unsupported market: {market!r} (expected 'us' or 'hk')")
    return normalized  # type: ignore[return-value]
