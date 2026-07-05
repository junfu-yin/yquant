"""S-A — US sector ETF momentum (03 §5.3, monthly, rule-based).

GICS 11 sector ETFs; take the top 3 by 12-1 momentum, equal weight. Rule-based
and fully backtestable, so it implements :class:`SignalProvider` with a rule
ModelCard (no knowledge cutoff) and can act as the champion in the champion-
challenger comparison for LLM satellites (09 §7).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from yquant.strategies.base import (
    ExplainContract,
    Inference,
    ModelCard,
    TargetPortfolio,
)
from yquant.strategies.indicators import total_return

if TYPE_CHECKING:
    from yquant.datasrc.protocols import DataRepo

# GICS 11 sector SPDR ETFs (defaults, overridable via config).
GICS_SECTOR_ETFS: tuple[str, ...] = (
    "XLK",  # Information Technology
    "XLF",  # Financials
    "XLE",  # Energy
    "XLV",  # Health Care
    "XLI",  # Industrials
    "XLY",  # Consumer Discretionary
    "XLP",  # Consumer Staples
    "XLU",  # Utilities
    "XLB",  # Materials
    "XLRE",  # Real Estate
    "XLC",  # Communication Services
)

PROVIDER_ID = "s_a_sector_momentum@1.0.0"


def sector_momentum_weights(
    monthly_prices: dict[str, list[float]],
    as_of: date,
    *,
    top_n: int = 3,
    budget: float = 1.0,
) -> TargetPortfolio:
    """Top-``top_n`` sector ETFs by 12-1 momentum, equal weight within budget."""

    if not 0.0 < budget <= 1.0:
        raise ValueError("budget must be in (0, 1]")

    momentum = {
        etf: total_return(prices, 12, skip=1)
        for etf, prices in monthly_prices.items()
        if etf in GICS_SECTOR_ETFS
    }
    ranked = sorted(momentum, key=lambda s: (-momentum[s], s))
    selected = ranked[:top_n]

    per = budget / len(selected) if selected else 0.0
    weights = dict.fromkeys(selected, per)
    return TargetPortfolio(
        as_of=as_of,
        weights=weights,
        layers=dict.fromkeys(weights, "satellite"),
        cash_weight=budget - sum(weights.values()),
    )


class SectorMomentumProvider:
    """S-A as a :class:`SignalProvider` (rule kind, backtestable, ADR-24 exempt)."""

    provider_id = PROVIDER_ID

    def __init__(self, lookback_months: int = 14, top_n: int = 3) -> None:
        self._lookback_months = lookback_months
        self._top_n = top_n

    def predict(self, as_of: date, universe: list[str], repo: DataRepo) -> list[Inference]:
        monthly = _monthly_closes(repo, as_of, universe, self._lookback_months)
        momentum = {
            etf: total_return(prices, 12, skip=1)
            for etf, prices in monthly.items()
            if etf in GICS_SECTOR_ETFS
        }
        ranked = sorted(momentum, key=lambda s: (-momentum[s], s))
        selected = set(ranked[: self._top_n])

        inferences: list[Inference] = []
        for etf in ranked:
            action = "buy" if etf in selected else "hold"
            inferences.append(
                Inference(
                    symbol=etf,
                    output=action,
                    confidence=1.0,  # deterministic rule
                    explain=ExplainContract(
                        kind="rule",
                        confidence=1.0,
                        regime_tag="sector_momentum",
                        evidence=[f"12-1 momentum={momentum[etf]:.4f}", "top-3 equal weight"],
                        caveats=["rule-based; no forward-looking edge is claimed"],
                    ),
                )
            )
        return inferences

    def model_card(self) -> ModelCard:
        return ModelCard(
            provider_id=self.provider_id,
            kind="rule",
            purpose="US GICS sector ETF 12-1 momentum, top 3 equal weight (monthly)",
            inputs=["monthly adjusted closes of GICS sector ETFs"],
            owner="research",
            known_limits=["single-factor; whipsaw in choppy regimes"],
            risks=["momentum crash on sharp reversals"],
        )


def _monthly_closes(
    repo: DataRepo,
    as_of: date,
    universe: list[str],
    lookback_months: int,
) -> dict[str, list[float]]:
    """Adapter placeholder: derive monthly closes from the repo.

    Concrete resampling (daily bars → month-end closes) lands with M1/backtest
    integration; kept minimal here so the provider's rule logic is complete and
    unit-testable via ``sector_momentum_weights``.
    """

    raise NotImplementedError(
        "monthly close resampling from DataRepo lands with M1 integration"
    )
