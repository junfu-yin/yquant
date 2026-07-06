"""Schemas for proposals and manual execution logs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from yquant.discipline.overlay_guardrails import InstrumentKind
from yquant.strategies.base import Layer


class TradeProposal(BaseModel):
    id: str
    created_at: datetime
    strategy: str
    symbol: str
    side: Literal["buy", "sell"]
    layer: Layer
    instrument_kind: InstrumentKind = "ordinary"
    is_system_signal: bool = True
    target_weight: float = Field(ge=0, le=1)
    suggested_shares: int = Field(ge=0)
    position_rule: str
    invalidation_condition: str
    red_team_note: str
    reason: str
    related_events: list[str]
    status: Literal["pending", "confirmed", "modified", "rejected", "expired"]

    @field_validator("position_rule", "invalidation_condition", "red_team_note", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field must not be empty")
        return cleaned
