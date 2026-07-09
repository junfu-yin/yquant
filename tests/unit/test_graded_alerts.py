"""WP7 graded-alert dedup + escalation tests (07 §5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from yquant.notify.graded import AlertRouter, GradedAlert


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


def test_fixed_source_severity_and_channels() -> None:
    router = AlertRouter()
    alert = router.route(
        source="layer_budget_breach", title="P11", text="budget", ts=_at(1)
    )
    assert isinstance(alert, GradedAlert)
    assert alert.severity == "S1"
    assert alert.channels == ("banner", "feishu")
    assert alert.runbook == "runbook §6.3"


def test_pillar_missing_is_s2_feishu_only() -> None:
    router = AlertRouter()
    alert = router.route(source="pillar_missing", title="P10", text="gap", ts=_at(1))
    assert alert is not None
    assert alert.severity == "S2"
    assert alert.channels == ("feishu",)


def test_dedup_suppresses_within_four_hour_window() -> None:
    router = AlertRouter()
    first = router.route(source="pillar_missing", title="P10", text="gap", ts=_at(1, 9))
    dup = router.route(
        source="pillar_missing", title="P10", text="gap", ts=_at(1, 12)
    )  # +3h
    assert first is not None
    assert dup is None


def test_dedup_releases_after_window() -> None:
    router = AlertRouter()
    router.route(source="pillar_missing", title="P10", text="gap", ts=_at(1, 9))
    later = router.route(
        source="pillar_missing", title="P10", text="gap", ts=_at(1, 9) + timedelta(hours=5)
    )
    assert later is not None


def test_s3_escalates_after_three_consecutive_days() -> None:
    router = AlertRouter()
    day1 = router.route(source="regime_change", title="rg", text="switch", ts=_at(1))
    day2 = router.route(source="regime_change", title="rg", text="switch", ts=_at(2))
    day3 = router.route(source="regime_change", title="rg", text="switch", ts=_at(3))

    assert day1 is not None and day1.severity == "S3"
    assert day2 is not None and day2.severity == "S3"
    assert day3 is not None
    assert day3.severity == "S2"
    assert day3.escalated_from == "S3"


def test_s3_does_not_escalate_when_days_not_consecutive() -> None:
    router = AlertRouter()
    router.route(source="regime_change", title="rg", text="switch", ts=_at(1))
    router.route(source="regime_change", title="rg", text="switch", ts=_at(2))
    gap = router.route(source="regime_change", title="rg", text="switch", ts=_at(5))
    assert gap is not None
    assert gap.severity == "S3"


def test_crisis_entry_is_s1() -> None:
    router = AlertRouter()
    alert = router.route(
        source="regime_change_crisis", title="crisis", text="enter", ts=_at(1)
    )
    assert alert is not None
    assert alert.severity == "S1"
    assert "banner" in alert.channels


def test_unknown_source_defaults_to_s3() -> None:
    router = AlertRouter()
    alert = router.route(source="mystery", title="m", text="t", ts=_at(1))
    assert alert is not None
    assert alert.severity == "S3"
    assert alert.runbook == "runbook §6.1"


def test_explicit_severity_override() -> None:
    router = AlertRouter()
    alert = router.route(
        source="pillar_missing", title="p", text="t", ts=_at(1), severity="S1"
    )
    assert alert is not None
    assert alert.severity == "S1"
