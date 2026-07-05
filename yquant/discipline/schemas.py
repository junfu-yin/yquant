"""Schemas for proposals and manual execution logs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TradeProposal(BaseModel):
    id: str
    created_at: datetime
    strategy: str
    symbol: str
    side: Literal["buy", "sell"]
    target_weight: float = Field(ge=0, le=1)
    suggested_shares: int = Field(ge=0)
    position_rule: str
    reason: str
    related_events: list[str]
    status: Literal["pending", "confirmed", "modified", "rejected", "expired"]

