"""WP8 drill台账 (06 §5, ADR-36): historical-event replays + a fire drill.

Process checks, not performance claims: every record must be contaminated. The
historical drills must traverse the state machine (deeper-drawdown windows push
closer to Crisis) and the fire drill must escalate fabricated events to S1 on
the banner + Feishu channels.
"""

from __future__ import annotations

from typing import Any, cast

from yquant.qa import build_drill_ledger, fire_drill, historical_event_drill
from yquant.qa.golden import GOLDEN_WINDOWS, get_window


def test_drill_ledger_covers_four_windows_plus_fire() -> None:
    records = build_drill_ledger()
    assert len(records) == len(GOLDEN_WINDOWS) + 1
    kinds = [r.kind for r in records]
    assert kinds.count("historical_event") == len(GOLDEN_WINDOWS)
    assert kinds.count("fire") == 1
    assert all(r.contaminated for r in records)


def test_covid_window_reaches_crisis() -> None:
    record = historical_event_drill(get_window("2020_covid"))
    assert record.detail["peak_severity"] == 3  # Crisis
    assert record.detail["end_state"] == "Crisis"


def test_deeper_drawdown_windows_stress_at_least_as_hard() -> None:
    covid = historical_event_drill(get_window("2020_covid"))
    carry = historical_event_drill(get_window("2024_carry"))
    assert cast(int, covid.detail["peak_severity"]) >= cast(int, carry.detail["peak_severity"])


def test_fire_drill_escalates_to_s1_banner_and_feishu() -> None:
    record = fire_drill()
    assert record.kind == "fire"
    alerts = cast(list[dict[str, Any]], record.detail["alerts"])
    assert len(alerts) == 2
    for alert in alerts:
        assert alert["severity"] == "S1"
        assert "banner" in alert["channels"]
        assert "feishu" in alert["channels"]


def test_drill_records_are_deterministic() -> None:
    first = build_drill_ledger()
    second = build_drill_ledger()
    assert [r.as_dict() for r in first] == [r.as_dict() for r in second]
