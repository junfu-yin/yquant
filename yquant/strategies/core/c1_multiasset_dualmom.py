"""C1 — global multi-asset dual momentum (03 §5.3, monthly).

Asset pool = eight sleeves, each realised via the most-liquid USD ETF:
US large / developed ex-US / emerging / US long bond / US intermediate bond /
gold / broad commodities / short bond (cash proxy).

Rule:
  - Relative momentum: composite rank of 12-1 and 6-1 total return; take top 3
    equal weight.
  - Absolute momentum filter: any selected sleeve whose 12-month return is below
    the short-bond sleeve's 12-month return falls to cash.

Pure function over monthly close series so it is unit-testable without a data
backend; a provider adapter (repo → monthly closes) lands with M1/scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from yquant.strategies.base import TargetPortfolio
from yquant.strategies.indicators import total_return


@dataclass(frozen=True)
class AssetSleeve:
    """One core-layer sleeve and the ETF that implements it."""

    name: str
    etf: str


# Default sleeves; the last one (short bond) is the cash proxy / absolute
# momentum benchmark. ETF tickers are defaults, overridable via config.
DEFAULT_ASSET_POOL: tuple[AssetSleeve, ...] = (
    AssetSleeve("us_large", "SPY"),
    AssetSleeve("developed_ex_us", "EFA"),
    AssetSleeve("emerging", "EEM"),
    AssetSleeve("us_long_bond", "TLT"),
    AssetSleeve("us_intermediate_bond", "IEF"),
    AssetSleeve("gold", "GLD"),
    AssetSleeve("commodities", "DBC"),
    AssetSleeve("short_bond_cash", "BIL"),
)

_CASH_SLEEVE = "BIL"


def dual_momentum_weights(
    monthly_prices: dict[str, list[float]],
    as_of: date,
    *,
    top_n: int = 3,
    budget: float = 1.0,
    cash_symbol: str = _CASH_SLEEVE,
) -> TargetPortfolio:
    """Compute the C1 target portfolio from monthly close series.

    ``monthly_prices`` maps ETF ticker -> monthly closes (oldest→newest, at least
    14 points so 12-1 momentum is defined). ``budget`` is the fraction of the
    whole book allotted to the core layer (default 1.0 for standalone use);
    weights and residual cash are scaled into it.
    """

    if not 0.0 < budget <= 1.0:
        raise ValueError("budget must be in (0, 1]")
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if cash_symbol not in monthly_prices:
        raise ValueError(f"cash proxy {cash_symbol!r} missing from monthly_prices")

    scores = _composite_scores(monthly_prices, cash_symbol)
    ranked = sorted(scores, key=lambda s: scores[s])  # lower composite rank = better
    selected = ranked[:top_n]

    cash_return = total_return(monthly_prices[cash_symbol], 12)
    survivors = [
        s for s in selected if total_return(monthly_prices[s], 12) >= cash_return
    ]

    weights: dict[str, float] = {}
    if survivors:
        per = budget / top_n  # dropped sleeves' slice becomes cash, not redistributed
        for symbol in survivors:
            weights[symbol] = per
    cash_weight = budget - sum(weights.values())

    return TargetPortfolio(
        as_of=as_of,
        weights=weights,
        layers=dict.fromkeys(weights, "core"),
        cash_weight=cash_weight,
    )


def _composite_scores(
    monthly_prices: dict[str, list[float]],
    cash_symbol: str,
) -> dict[str, float]:
    """Composite rank (12-1 rank + 6-1 rank); lower is better. Cash excluded."""

    candidates = [s for s in monthly_prices if s != cash_symbol]
    r_12_1 = {s: total_return(monthly_prices[s], 12, skip=1) for s in candidates}
    r_6_1 = {s: total_return(monthly_prices[s], 6, skip=1) for s in candidates}

    rank_12 = _ranks(r_12_1)
    rank_6 = _ranks(r_6_1)
    return {s: rank_12[s] + rank_6[s] for s in candidates}


def _ranks(values: dict[str, float]) -> dict[str, int]:
    """Rank 1 = highest value; ties broken by symbol for determinism."""

    ordered = sorted(values, key=lambda s: (-values[s], s))
    return {symbol: i + 1 for i, symbol in enumerate(ordered)}
