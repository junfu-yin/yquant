"""Overlay and icebox guardrails from v3.1a.

This module is intentionally pure. It does not decide whether an opportunity is
good; it only decides whether a proposed expression is allowed by the signed
budget and instrument rules. Confidence never overrides these caps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from yquant.risk.regime import RiskRegime
from yquant.strategies.base import Layer

InstrumentKind = Literal[
    "ordinary",
    "leveraged_2x_long",
    "leveraged_3x",
    "inverse",
    "meme_stock",
    "discretionary",
]


@dataclass(frozen=True)
class OverlayGuardrailConfig:
    """Hard v3.1a caps for the tactical Overlay layer."""

    overlay_cap: float = 0.10
    overlay_single_cap: float = 0.05
    leveraged_2x_total_cap: float = 0.05
    leveraged_2x_single_cap: float = 0.03
    icebox_tickers: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "SQQQ",
                "TQQQ",
                "UPRO",
                "TMF",
                "SDS",
                "SPXU",
                "SH",
            }
        )
    )


@dataclass(frozen=True)
class OverlayExposure:
    """Post-trade exposures used to validate an Overlay request."""

    overlay_weight_after: float
    symbol_weight_after: float
    leveraged_2x_weight_after: float = 0.0
    confidence: float | None = None


@dataclass(frozen=True)
class OverlayViolation:
    """One guardrail breach, suitable for a risk_event detail."""

    rule: str
    detail: dict[str, float | str | None]


def required_layer_for_request(
    requested_layer: Layer,
    *,
    instrument_kind: InstrumentKind,
    is_system_signal: bool,
) -> Layer:
    """Return the layer a request must use under ADR-37."""

    if not is_system_signal or instrument_kind != "ordinary":
        return "overlay"
    return requested_layer


def validate_overlay_request(
    *,
    symbol: str,
    instrument_kind: InstrumentKind,
    exposure: OverlayExposure,
    config: OverlayGuardrailConfig | None = None,
    risk_regime: RiskRegime | None = None,
) -> list[OverlayViolation]:
    """Validate an Overlay expression against v3.1a hard limits.

    When ``risk_regime`` is supplied, a 2x-long request is additionally gated on
    ``risk_regime.risk_on``: leverage is refused in a risk-off backdrop. Omitting
    ``risk_regime`` leaves the static caps unchanged (no dynamic gate).
    """

    config = config or OverlayGuardrailConfig()
    ticker = symbol.upper()
    violations: list[OverlayViolation] = []

    if (
        instrument_kind == "leveraged_2x_long"
        and risk_regime is not None
        and not risk_regime.risk_on
    ):
        violations.append(
            OverlayViolation(
                rule="leveraged_2x_risk_off",
                detail={"symbol": ticker, "kind": instrument_kind, "reason": risk_regime.reason},
            )
        )

    if ticker in config.icebox_tickers:
        violations.append(
            OverlayViolation(
                rule="icebox_ticker",
                detail={"symbol": ticker, "kind": instrument_kind, "cap": None},
            )
        )

    if instrument_kind in {"leveraged_3x", "inverse"}:
        violations.append(
            OverlayViolation(
                rule=f"{instrument_kind}_not_allowed",
                detail={"symbol": ticker, "kind": instrument_kind, "cap": None},
            )
        )

    if exposure.overlay_weight_after > config.overlay_cap:
        violations.append(
            OverlayViolation(
                rule="overlay_cap",
                detail={
                    "symbol": ticker,
                    "weight_after": round(exposure.overlay_weight_after, 6),
                    "cap": config.overlay_cap,
                },
            )
        )

    if exposure.symbol_weight_after > config.overlay_single_cap:
        violations.append(
            OverlayViolation(
                rule="overlay_single_cap",
                detail={
                    "symbol": ticker,
                    "weight_after": round(exposure.symbol_weight_after, 6),
                    "cap": config.overlay_single_cap,
                },
            )
        )

    if instrument_kind == "leveraged_2x_long":
        if exposure.leveraged_2x_weight_after > config.leveraged_2x_total_cap:
            violations.append(
                OverlayViolation(
                    rule="leveraged_2x_total_cap",
                    detail={
                        "symbol": ticker,
                        "weight_after": round(exposure.leveraged_2x_weight_after, 6),
                        "cap": config.leveraged_2x_total_cap,
                    },
                )
            )
        if exposure.symbol_weight_after > config.leveraged_2x_single_cap:
            violations.append(
                OverlayViolation(
                    rule="leveraged_2x_single_cap",
                    detail={
                        "symbol": ticker,
                        "weight_after": round(exposure.symbol_weight_after, 6),
                        "cap": config.leveraged_2x_single_cap,
                    },
                )
            )

    return violations
