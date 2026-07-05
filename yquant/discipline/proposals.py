"""M5 proposal builder (03 §5.5).

Converts the risk-controlled :class:`TargetPortfolio` (post-M8) plus current
holdings into :class:`TradeProposal` records. Share counts respect the minimum
trading unit: US 1 share (or fractional if enabled), HK by per-symbol lot size.
Proposals are suggestions only — never orders (ADR-22).
"""

from __future__ import annotations

import math
from datetime import datetime

from yquant.discipline.schemas import TradeProposal
from yquant.strategies.base import TargetPortfolio


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
) -> list[TradeProposal]:
    """Diff target vs current weights into buy/sell proposals.

    Only weight moves larger than ``min_weight_change`` produce a proposal (to
    suppress churn). ``reason`` cites the strategy, not an LLM (03 §5.5).
    """

    lot_sizes = lot_sizes or {}
    related_events = related_events or {}
    created_at = now or datetime.now()
    proposals: list[TradeProposal] = []

    symbols = set(controlled.weights) | set(current_weights)
    for symbol in sorted(symbols):
        target = controlled.weights.get(symbol, 0.0)
        current = current_weights.get(symbol, 0.0)
        delta = target - current
        if abs(delta) < min_weight_change:
            continue

        side = "buy" if delta > 0 else "sell"
        price = prices.get(symbol)
        if price is None:
            continue
        target_value = target * portfolio_value
        shares = suggested_shares(
            target_value,
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
                target_weight=max(0.0, min(1.0, target)),
                suggested_shares=int(shares),
                position_rule=position_rule,
                reason=f"{strategy}: target weight {target:.4f} vs current {current:.4f}",
                related_events=related_events.get(symbol, []),
                status="pending",
            )
        )
    return proposals
