"""M5 discipline risk rules (03 §5.5): pure, no LLM.

Encodes the position/industry caps, drawdown lines and the consecutive-loss
cooldown. Every trigger is meant to be recorded to ``risk_events`` (03 §7).
These are portfolio-hygiene rules distinct from the M8 pre-trade engine: M8
shapes target weights; these gate a manual buy/sell decision and drive the
execution checklist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class DisciplineConfig:
    """Configurable discipline thresholds (03 §5.5 defaults)."""

    single_name_cap: float = 0.15
    industry_cap: float = 0.35
    drawdown_alert: float = 0.10
    drawdown_strong: float = 0.15
    consecutive_loss_limit: int = 3
    cooldown_trading_days: int = 3


@dataclass(frozen=True)
class RuleViolation:
    """A discipline rule outcome; ``blocking=False`` means "warn + confirm"."""

    rule: str
    blocking: bool
    detail: dict[str, Any]


@dataclass
class DisciplineState:
    """Rolling portfolio state the rules read (owned by the journal layer)."""

    drawdown: float = 0.0  # current portfolio drawdown, >= 0
    recent_trade_pnl: list[float] = field(default_factory=list)  # oldest→newest realised P&L
    cooldown_until: date | None = None


def check_position_caps(
    side: Side,
    symbol: str,
    prospective_weight: float,
    industry_weight_after: float,
    config: DisciplineConfig,
) -> list[RuleViolation]:
    """Single-name and industry cap checks for a prospective buy.

    Sells never breach caps (they reduce exposure), so only buys are checked.
    """

    if side == "sell":
        return []
    violations: list[RuleViolation] = []
    if prospective_weight > config.single_name_cap:
        violations.append(
            RuleViolation(
                rule="single_name_cap",
                blocking=True,
                detail={
                    "symbol": symbol,
                    "prospective_weight": round(prospective_weight, 6),
                    "cap": config.single_name_cap,
                },
            )
        )
    if industry_weight_after > config.industry_cap:
        violations.append(
            RuleViolation(
                rule="industry_cap",
                blocking=True,
                detail={
                    "industry_weight_after": round(industry_weight_after, 6),
                    "cap": config.industry_cap,
                },
            )
        )
    return violations


def check_drawdown(
    side: Side,
    state: DisciplineState,
    config: DisciplineConfig,
) -> list[RuleViolation]:
    """Drawdown gate: block *adding* (buy) beyond the strong line; warn past alert."""

    if side == "sell":
        return []
    if state.drawdown >= config.drawdown_strong:
        return [
            RuleViolation(
                rule="drawdown_strong",
                blocking=True,
                detail={"drawdown": round(state.drawdown, 6), "line": config.drawdown_strong},
            )
        ]
    if state.drawdown >= config.drawdown_alert:
        return [
            RuleViolation(
                rule="drawdown_alert",
                blocking=False,
                detail={"drawdown": round(state.drawdown, 6), "line": config.drawdown_alert},
            )
        ]
    return []


def is_in_cooldown(state: DisciplineState, on_date: date) -> bool:
    """Whether a consecutive-loss cooldown is still active on ``on_date``."""

    return state.cooldown_until is not None and on_date <= state.cooldown_until


def triggers_cooldown(state: DisciplineState, config: DisciplineConfig) -> bool:
    """Whether the last N realised trades are all losses (cooldown trigger)."""

    limit = config.consecutive_loss_limit
    if len(state.recent_trade_pnl) < limit:
        return False
    return all(pnl < 0 for pnl in state.recent_trade_pnl[-limit:])


def check_cooldown(
    state: DisciplineState,
    on_date: date,
    config: DisciplineConfig,
) -> list[RuleViolation]:
    """Cooldown gate: opening a new position during cooldown warns + confirms."""

    if is_in_cooldown(state, on_date):
        return [
            RuleViolation(
                rule="cooldown",
                blocking=False,
                detail={
                    "cooldown_until": state.cooldown_until.isoformat()
                    if state.cooldown_until
                    else None
                },
            )
        ]
    return []
