"""C2 — trend gate (03 §5.3, monthly).

Each asset below its 10-month moving average is not held. Redundant with C1's
absolute-momentum filter by design. This module computes the per-symbol trend
status that M8's ``trend_gate`` mechanism consumes (``RiskInputs.trend_ok``), so
the rule lives in exactly one place.
"""

from __future__ import annotations

from yquant.strategies.indicators import moving_average

DEFAULT_TREND_WINDOW = 10  # months


def is_above_trend(
    monthly_prices: list[float],
    window: int = DEFAULT_TREND_WINDOW,
) -> bool:
    """Return whether the latest monthly close is at/above its N-month MA."""

    ma = moving_average(monthly_prices, window)
    return monthly_prices[-1] >= ma


def trend_status(
    monthly_prices: dict[str, list[float]],
    window: int = DEFAULT_TREND_WINDOW,
) -> dict[str, bool]:
    """Map each symbol to its trend-gate pass/fail for ``RiskInputs.trend_ok``."""

    return {
        symbol: is_above_trend(prices, window)
        for symbol, prices in monthly_prices.items()
        if len(prices) >= window
    }
