"""Risk-on / risk-off regime for dynamic leverage gating.

The v3.1a overlay allows a small 2x-long ETF sleeve, but leverage should only be
extended when the market backdrop supports it. This module turns a market trend
flag and a VIX level into a single ``risk_on`` decision the overlay guardrails
consume.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskRegime:
    """Whether the backdrop permits extending leverage (2x long)."""

    risk_on: bool
    reason: str = ""


def compute_risk_on(
    *,
    market_trend_ok: bool,
    vix_level: float | None,
    vix_threshold: float = 25.0,
) -> RiskRegime:
    """Risk-on only when the market is in an uptrend and VIX is not elevated.

    A missing ``vix_level`` is treated as non-blocking (trend decides), so the
    gate degrades to trend-only when macro data is unavailable rather than
    silently forcing risk-off.
    """

    if vix_threshold <= 0:
        raise ValueError("vix_threshold must be positive")

    if not market_trend_ok:
        return RiskRegime(risk_on=False, reason="market_trend_down")
    if vix_level is not None and vix_level > vix_threshold:
        return RiskRegime(
            risk_on=False,
            reason=f"vix_{vix_level:.2f}_above_{vix_threshold:.2f}",
        )
    return RiskRegime(risk_on=True, reason="trend_up_vix_ok")
