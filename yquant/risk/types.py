"""M8 risk engine: event-driven risk ledger types (03 §5.8, 12 §5)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class RiskState:
    """Configuration for the four M8 pre-trade control mechanisms.

    Defaults follow 03 §5.8: ``target_vol`` 11% (band 10-12%), vol-target trigger
    at 1.15x, circuit-breaker at 1.5x for two consecutive weeks, single-holding
    liquidation cap 20% of ADV. ``target_vol_floor`` is the bottom of the 10-12%
    band the regime gate tightens to in Crisis (03 §5.8 ④ / §5.9, 13 §7 S2).
    """

    target_vol: float = 0.11
    target_vol_floor: float = 0.10
    concentration_caps: dict[str, float] = field(default_factory=dict)
    adv_liquidation_cap: float = 0.20
    vol_target_trigger_ratio: float = 1.15
    circuit_breaker_ratio: float = 1.5
    drawdown_freeze_at: float = 0.10
    drawdown_liquidate_at: float = 0.15


@dataclass(frozen=True)
class RiskEvent:
    """A single ledger event emitted by an M8 mechanism (replayable, 07).

    Maps to the ``risk_events(id, date, rule, detail_json)`` table (03 §7).
    ``detail`` values must be JSON-safe scalars.
    """

    as_of: date
    rule: str
    detail: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        """Serialize into a ``risk_events`` row (id assigned at persist time)."""

        return {"date": self.as_of.isoformat(), "rule": self.rule, "detail_json": self.detail}


@dataclass(frozen=True)
class RiskInputs:
    """Numeric inputs the four mechanisms operate on (built from DataRepo).

    Separated from the repo so the mechanisms stay pure and unit-testable with a
    hand-built instance (03 §5.8 acceptance uses synthetic data for T14/T15).

    - ``predicted_annual_vol``: EWMA-based forecast of portfolio annual vol.
    - ``weekly_realized_vol``: recent weekly realized vols (oldest→newest); the
      circuit breaker inspects the last two.
    - ``adv``: average daily turnover (amount) per symbol.
    - ``position_value``: current market value per held symbol.
    - ``portfolio_value``: total portfolio value (positions + cash); used to
      convert target weights to values for the crowding sentinel.
    - ``asset_classes``: symbol -> class (equity/bond/gold/commodity/cash); the
      vol targeter only scales ``equity``.
    - ``trend_ok``: symbol -> whether it is above its 10-month MA (C2 gate).
    - ``portfolio_drawdown``: current peak-to-trough drawdown (>= 0); the
      drawdown circuit ladder (§5.8 ④) freezes adds at 10% and liquidates the
      Overlay sleeve at 15%.
    """

    predicted_annual_vol: float
    weekly_realized_vol: Sequence[float] = ()
    adv: dict[str, float] = field(default_factory=dict)
    position_value: dict[str, float] = field(default_factory=dict)
    portfolio_value: float = 0.0
    asset_classes: dict[str, str] = field(default_factory=dict)
    trend_ok: dict[str, bool] = field(default_factory=dict)
    portfolio_drawdown: float = 0.0
