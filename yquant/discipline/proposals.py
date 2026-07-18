"""M5 proposal builder (03 §5.5).

Converts the risk-controlled :class:`TargetPortfolio` (post-M8) plus current
holdings into :class:`TradeProposal` records. Proposal metadata is mandatory:
v3.1a requires every suggestion to carry a machine-readable invalidation
condition and a red-team note before it can enter the journal. Proposals are
suggestions only — never orders (ADR-22).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from yquant.discipline.overlay_guardrails import (
    InstrumentKind,
    OverlayExposure,
    OverlayGuardrailConfig,
    OverlayViolation,
    required_layer_for_request,
    validate_overlay_request,
)
from yquant.discipline.schemas import TradeProposal
from yquant.risk.regime import RiskRegime
from yquant.strategies.base import Layer, TargetPortfolio


@dataclass(frozen=True)
class ProposalMetadata:
    """Per-symbol governance metadata required to create a proposal."""

    invalidation_condition: str
    red_team_note: str
    instrument_kind: InstrumentKind = "ordinary"
    is_system_signal: bool = True
    requested_layer: Layer | None = None


class ProposalValidationError(ValueError):
    """Raised when a proposal would violate v3.1a governance rules."""

    def __init__(
        self,
        message: str,
        *,
        symbol: str | None = None,
        violations: list[OverlayViolation] | None = None,
    ) -> None:
        super().__init__(message)
        self.symbol = symbol
        self.violations = violations or []


def suggested_shares(
    target_value: float,
    price: float,
    *,
    lot_size: int = 1,
    allow_fractional: bool = False,
) -> float:
    """Shares implied by a target value at ``price``, floored to the lot size.

    Returns a float so fractional US shares are representable; callers that need
    an int (whole-share markets) get an integral float when ``allow_fractional``
    is False.
    """

    if price <= 0:
        raise ValueError("price must be positive")
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    raw = target_value / price
    if allow_fractional:
        return raw
    lots = math.floor(raw / lot_size)
    return float(lots * lot_size)


def build_proposals(
    controlled: TargetPortfolio,
    current_weights: dict[str, float],
    prices: dict[str, float],
    portfolio_value: float,
    *,
    strategy: str,
    position_rule: str,
    lot_sizes: dict[str, int] | None = None,
    allow_fractional: bool = False,
    min_weight_change: float = 0.005,
    now: datetime | None = None,
    related_events: dict[str, list[str]] | None = None,
    proposal_metadata: dict[str, ProposalMetadata] | None = None,
    overlay_config: OverlayGuardrailConfig | None = None,
    risk_regime: RiskRegime | None = None,
) -> list[TradeProposal]:
    """Diff target vs current weights into buy/sell proposals.

    Only weight moves larger than ``min_weight_change`` produce a proposal (to
    suppress churn). ``reason`` cites the strategy, not an LLM (03 §5.5).
    Symbols that emit a proposal must have :class:`ProposalMetadata`.
    """

    lot_sizes = lot_sizes or {}
    related_events = related_events or {}
    proposal_metadata = proposal_metadata or {}
    if not math.isfinite(portfolio_value) or portfolio_value <= 0:
        raise ValueError("portfolio_value must be finite and positive")
    if not math.isfinite(min_weight_change) or min_weight_change < 0:
        raise ValueError("min_weight_change must be finite and non-negative")
    if any(not math.isfinite(weight) or weight < 0 for weight in current_weights.values()):
        raise ValueError("current_weights must be finite and non-negative")
    created_at = now or datetime.now(UTC)
    proposals: list[TradeProposal] = []
    effective_layers = _effective_target_layers(controlled, proposal_metadata)
    overlay_weight_after = _overlay_weight_after(controlled, effective_layers)
    leveraged_2x_weight_after = _leveraged_2x_weight_after(controlled, proposal_metadata)

    symbols = set(controlled.weights) | set(current_weights)
    for symbol in sorted(symbols):
        target = controlled.weights.get(symbol, 0.0)
        current = current_weights.get(symbol, 0.0)
        delta = target - current
        if abs(delta) < min_weight_change:
            continue

        side: Literal["buy", "sell"] = "buy" if delta > 0 else "sell"
        metadata = _required_metadata(symbol, proposal_metadata)
        requested_layer = metadata.requested_layer or controlled.layers.get(symbol, "overlay")
        layer = required_layer_for_request(
            requested_layer,
            instrument_kind=metadata.instrument_kind,
            is_system_signal=metadata.is_system_signal,
        )
        _validate_required_metadata(symbol, metadata)
        if side == "buy":
            _validate_guardrails(
                symbol=symbol,
                layer=layer,
                metadata=metadata,
                overlay_weight_after=overlay_weight_after,
                symbol_weight_after=max(0.0, target),
                leveraged_2x_weight_after=leveraged_2x_weight_after,
                overlay_config=overlay_config,
                risk_regime=risk_regime,
            )
        price = prices.get(symbol)
        if price is None:
            continue
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"price for {symbol} must be finite and positive")
        trade_value = abs(delta) * portfolio_value
        shares = suggested_shares(
            trade_value,
            price,
            lot_size=lot_sizes.get(symbol, 1),
            allow_fractional=allow_fractional,
        )
        proposals.append(
            TradeProposal(
                id=f"{symbol}-{created_at.isoformat()}",
                created_at=created_at,
                strategy=strategy,
                symbol=symbol,
                side=side,
                layer=layer,
                instrument_kind=metadata.instrument_kind,
                is_system_signal=metadata.is_system_signal,
                target_weight=max(0.0, min(1.0, target)),
                suggested_shares=int(shares),
                position_rule=position_rule,
                invalidation_condition=metadata.invalidation_condition,
                red_team_note=metadata.red_team_note,
                reason=(
                    f"{strategy}: target weight {target:.4f} vs current {current:.4f} "
                    f"(delta {delta:+.4f})"
                ),
                related_events=related_events.get(symbol, []),
                status="pending",
            )
        )
    return proposals


def _required_metadata(
    symbol: str,
    proposal_metadata: dict[str, ProposalMetadata],
) -> ProposalMetadata:
    metadata = proposal_metadata.get(symbol)
    if metadata is None:
        raise ProposalValidationError(
            f"proposal metadata is required for {symbol}",
            symbol=symbol,
        )
    return metadata


def _validate_required_metadata(symbol: str, metadata: ProposalMetadata) -> None:
    if not metadata.invalidation_condition.strip():
        raise ProposalValidationError(
            f"invalidation_condition is required for {symbol}",
            symbol=symbol,
        )
    if not metadata.red_team_note.strip():
        raise ProposalValidationError(
            f"red_team_note is required for {symbol}",
            symbol=symbol,
        )


def _effective_target_layers(
    controlled: TargetPortfolio,
    proposal_metadata: dict[str, ProposalMetadata],
) -> dict[str, Layer]:
    layers: dict[str, Layer] = {}
    for symbol in controlled.weights:
        metadata = proposal_metadata.get(symbol)
        requested_layer = (
            metadata.requested_layer
            if metadata and metadata.requested_layer
            else controlled.layers.get(symbol, "overlay")
        )
        instrument_kind: InstrumentKind = metadata.instrument_kind if metadata else "ordinary"
        is_system_signal = metadata.is_system_signal if metadata else True
        layers[symbol] = required_layer_for_request(
            requested_layer,
            instrument_kind=instrument_kind,
            is_system_signal=is_system_signal,
        )
    return layers


def _overlay_weight_after(
    controlled: TargetPortfolio,
    effective_layers: dict[str, Layer],
) -> float:
    return sum(
        weight
        for symbol, weight in controlled.weights.items()
        if effective_layers.get(symbol) == "overlay"
    )


def _leveraged_2x_weight_after(
    controlled: TargetPortfolio,
    proposal_metadata: dict[str, ProposalMetadata],
) -> float:
    return sum(
        weight
        for symbol, weight in controlled.weights.items()
        if proposal_metadata.get(symbol)
        and proposal_metadata[symbol].instrument_kind == "leveraged_2x_long"
    )


def _validate_guardrails(
    *,
    symbol: str,
    layer: Layer,
    metadata: ProposalMetadata,
    overlay_weight_after: float,
    symbol_weight_after: float,
    leveraged_2x_weight_after: float,
    overlay_config: OverlayGuardrailConfig | None,
    risk_regime: RiskRegime | None,
) -> None:
    if layer != "overlay":
        return
    violations = validate_overlay_request(
        symbol=symbol,
        instrument_kind=metadata.instrument_kind,
        exposure=OverlayExposure(
            overlay_weight_after=overlay_weight_after,
            symbol_weight_after=symbol_weight_after,
            leveraged_2x_weight_after=leveraged_2x_weight_after,
        ),
        config=overlay_config,
        risk_regime=risk_regime,
    )
    if violations:
        rules = ", ".join(violation.rule for violation in violations)
        raise ProposalValidationError(
            f"proposal for {symbol} violates guardrails: {rules}",
            symbol=symbol,
            violations=violations,
        )
