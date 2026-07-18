from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from yquant.config import load_config
from yquant.datasrc.freshness import DailyBarFreshnessItem, DailyBarFreshnessReport
from yquant.datasrc.reconcile import ReconciliationMismatch, ReconciliationReport
from yquant.datasrc.reconcile_live import (
    SampledLiveReconciliationReport,
    SourceFetchOutcome,
)
from yquant.notify import (
    AlertMessage,
    FeishuNotifier,
    freshness_alert,
    live_reconcile_alert,
    notifier_from_env,
    reconcile_alert,
)


def _freshness_report(status: str) -> DailyBarFreshnessReport:
    item = DailyBarFreshnessItem(
        symbol="AAPL",
        expected_date=date(2024, 1, 31),
        latest_date=date(2024, 1, 30) if status != "fresh" else date(2024, 1, 31),
        latest_asof_utc=None,
        status=status,  # type: ignore[arg-type]
        detail="detail text",
    )
    return DailyBarFreshnessReport(
        dataset="daily_bars",
        expected_date=date(2024, 1, 31),
        deadline_utc=None,
        generated_at_utc=datetime(2024, 2, 1, tzinfo=UTC),
        items=(item,),
    )


def test_freshness_alert_is_none_when_fresh() -> None:
    assert freshness_alert(_freshness_report("fresh")) is None


def test_freshness_alert_lists_stale_symbols() -> None:
    message = freshness_alert(_freshness_report("stale"))
    assert message is not None
    assert "1 symbol(s) not fresh" in message.title
    assert "AAPL" in message.text
    assert "stale" in message.text


def _reconcile_report(*, passed: bool) -> ReconciliationReport:
    mismatches = (
        ()
        if passed
        else (
            ReconciliationMismatch(
                symbol="AAPL",
                date=date(2024, 1, 3),
                left_value=100.0,
                right_value=110.0,
                diff_bps=1000.0,
            ),
        )
    )
    return ReconciliationReport(
        dataset="daily_bars",
        left_source="yfinance",
        right_source="stooq",
        tolerance_bps=10.0,
        minimum_consistency_rate=0.995,
        compared_rows=100,
        missing_left_rows=0,
        missing_right_rows=0,
        mismatches=mismatches,
    )


def test_reconcile_alert_is_none_when_passing() -> None:
    assert reconcile_alert(_reconcile_report(passed=True)) is None


def test_reconcile_alert_reports_consistency() -> None:
    message = reconcile_alert(_reconcile_report(passed=False))
    assert message is not None
    assert "below threshold" in message.title
    assert "consistency_rate" in message.text


def _live_report(*, failed: bool) -> SampledLiveReconciliationReport:
    reconciliation = _reconcile_report(passed=True)
    left = (SourceFetchOutcome("AAPL", "yfinance", "failed"),) if failed else ()
    return SampledLiveReconciliationReport(
        dataset="daily_bars",
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        universe_size=1,
        sample_size=1,
        seed=1,
        sampled_symbols=("AAPL",),
        left_fetches=left,
        right_fetches=(),
        reconciliation=reconciliation,
    )


def test_live_reconcile_alert_is_none_when_passing() -> None:
    assert live_reconcile_alert(_live_report(failed=False)) is None


def test_live_reconcile_alert_reports_fetch_failures() -> None:
    message = live_reconcile_alert(_live_report(failed=True))
    assert message is not None
    assert "left_fetch_failures" in message.text


def test_requests_transport_posts_and_raises_for_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    calls: list[tuple[str, dict[str, Any]]] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

    def _post(url: str, json: dict[str, Any], timeout: int) -> _Resp:
        calls.append((url, json))
        return _Resp()

    fake_requests = types.ModuleType("requests")
    fake_requests.post = _post  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    notifier = FeishuNotifier("https://example.test/hook")
    notifier.send(AlertMessage(title="T", text="b"))

    assert calls[0][0] == "https://example.test/hook"


def test_feishu_notifier_posts_text_payload() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    notifier = FeishuNotifier(
        "https://example.test/hook",
        transport=lambda u, p: sent.append((u, p)),
    )

    notifier.send(AlertMessage(title="T", text="body"))

    assert len(sent) == 1
    url, payload = sent[0]
    assert url == "https://example.test/hook"
    assert payload["msg_type"] == "text"
    assert payload["content"]["text"] == "T\nbody"


def test_feishu_notifier_rejects_empty_url() -> None:
    with pytest.raises(ValueError, match="webhook_url"):
        FeishuNotifier("   ")


def test_feishu_notifier_rejects_non_https_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        FeishuNotifier("http://example.test/hook")


def test_notifier_from_env_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config("config.example.toml")
    monkeypatch.delenv(cfg.notification.feishu.webhook_env, raising=False)
    assert notifier_from_env(cfg) is None


def test_notifier_from_env_builds_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config("config.example.toml")
    monkeypatch.setenv(cfg.notification.feishu.webhook_env, "https://example.test/hook")
    notifier = notifier_from_env(cfg, transport=lambda u, p: None)
    assert isinstance(notifier, FeishuNotifier)
