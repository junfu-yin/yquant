from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from yquant.brief.schemas import EventCard
from yquant.discipline.schemas import TradeProposal


def test_event_card_schema_accepts_valid_card() -> None:
    card = EventCard(
        symbol="600000",
        source_type="announcement",
        event_type="减持",
        severity=4,
        direction="利空",
        one_line="股东披露减持计划",
        key_numbers=["1000万股"],
        rationale="减持规模较大",
        source_url="https://example.com/a",
        prompt_version="brief_v1",
    )

    assert card.severity == 4
    assert str(card.source_url) == "https://example.com/a"


def test_event_card_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        EventCard(
            symbol="600000",
            source_type="announcement",
            event_type="减持",
            severity=6,
            direction="利空",
            one_line="股东披露减持计划",
            key_numbers=[],
            rationale="减持规模较大",
            source_url="https://example.com/a",
            prompt_version="brief_v1",
        )


def test_trade_proposal_schema() -> None:
    proposal = TradeProposal(
        id="p1",
        created_at=datetime(2026, 7, 5, 9, 0, tzinfo=UTC),
        strategy="S2",
        symbol="600000",
        side="buy",
        target_weight=0.05,
        suggested_shares=1000,
        position_rule="single<=15%",
        reason="strategy rule",
        related_events=["e1"],
        status="pending",
    )

    assert proposal.status == "pending"

