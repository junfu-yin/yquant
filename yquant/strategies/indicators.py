"""Pure numeric indicators shared by strategies and the risk engine (03 §5.3/§5.8).

Kept dependency-light (standard library only) so every consumer—core/satellite
strategies and the M8 risk inputs builder—can be unit-tested without a data
backend. Prices/returns are passed as plain sequences ordered oldest→newest.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

TRADING_DAYS_PER_YEAR = 252
TRADING_MONTHS_PER_YEAR = 12


def daily_returns(prices: Sequence[float]) -> list[float]:
    """Simple period-over-period returns from a price series (oldest→newest)."""

    out: list[float] = []
    for prev, cur in zip(prices, prices[1:], strict=False):
        if prev == 0:
            raise ValueError("cannot compute return from a zero price")
        out.append(cur / prev - 1.0)
    return out


def moving_average(values: Sequence[float], window: int) -> float:
    """Trailing simple moving average over the last ``window`` values."""

    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        raise ValueError(f"need at least {window} values, got {len(values)}")
    return sum(values[-window:]) / window


def total_return(prices: Sequence[float], lookback: int, skip: int = 0) -> float:
    """Return over ``lookback`` periods ending ``skip`` periods before the last.

    ``skip=1`` implements the momentum convention that drops the most recent
    period (e.g. 12-1 momentum = 12-month return excluding the latest month).
    """

    if lookback <= 0:
        raise ValueError("lookback must be positive")
    end = len(prices) - 1 - skip
    start = end - lookback
    if start < 0:
        raise ValueError(f"need at least {lookback + skip + 1} prices, got {len(prices)}")
    if prices[start] == 0:
        raise ValueError("cannot compute return from a zero price")
    return prices[end] / prices[start] - 1.0


def annualized_vol(
    returns: Sequence[float],
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualized volatility from a return series (population std, unbiased-free)."""

    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(variance) * math.sqrt(periods_per_year)


def ewma_annualized_vol(
    returns: Sequence[float],
    lam: float = 0.94,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """RiskMetrics-style EWMA annualized volatility (recent obs weighted more)."""

    if not 0.0 < lam < 1.0:
        raise ValueError("lam must be in (0, 1)")
    n = len(returns)
    if n < 2:
        return 0.0
    # Newest return gets weight (1-lam); older ones decay by lam each step.
    weights = [(1.0 - lam) * lam**i for i in range(n)]
    ordered = list(reversed(returns))  # index 0 = newest
    total_w = sum(weights)
    weights = [w / total_w for w in weights]
    mean = sum(w * r for w, r in zip(weights, ordered, strict=True))
    variance = sum(w * (r - mean) ** 2 for w, r in zip(weights, ordered, strict=True))
    return math.sqrt(variance) * math.sqrt(periods_per_year)


def portfolio_returns(
    weights: Mapping[str, float],
    per_symbol_returns: Mapping[str, Sequence[float]],
) -> list[float]:
    """Weighted portfolio return series from aligned per-symbol return series."""

    active = {s: w for s, w in weights.items() if w != 0 and s in per_symbol_returns}
    if not active:
        return []
    length = min(len(per_symbol_returns[s]) for s in active)
    out: list[float] = []
    for t in range(length):
        out.append(sum(w * per_symbol_returns[s][-length + t] for s, w in active.items()))
    return out
