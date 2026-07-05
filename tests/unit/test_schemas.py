from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from yquant.brief.schemas import EventCard
from yquant.discipline.schemas import TradeProposal


def test_event_card_schema_accepts_valid_card() -> None:
    card = EventCard(
        symbol="AAPL",
        market="us",
        source_type="announcement",
        event_type="内部人交易",
        severity=4,
        direction="利空",
        one_line="Director filed Form 4 disclosing a share sale",
        key_numbers=["10,000 shares"],
        rationale="Sizable insider sale",
        source_url="https://www.sec.gov/cgi-bin/browse-edgar",
        prompt_version="brief_v1",
    )

    assert card.severity == 4
    assert card.market == "us"
    assert str(card.source_url) == "https://www.sec.gov/cgi-bin/browse-edgar"


def test_event_card_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        EventCard(
            symbol="0700.HK",
            market="hk",
            source_type="announcement",
            event_type="内部人交易",
            severity=6,
            direction="利空",
            one_line="Substantial shareholder reduced holdings",
            key_numbers=[],
            rationale="Sizable disposal",
            source_url="https://www1.hkexnews.hk/",
            prompt_version="brief_v1",
        )


def test_trade_proposal_schema() -> None:
    proposal = TradeProposal(
        id="p1",
        created_at=datetime(2026, 7, 5, 9, 0, tzinfo=UTC),
        strategy="S2",
        symbol="AAPL",
        side="buy",
        target_weight=0.05,
        suggested_shares=100,
        position_rule="single<=15%",
        reason="strategy rule",
        related_events=["e1"],
        status="pending",
    )

    assert proposal.status == "pending"

