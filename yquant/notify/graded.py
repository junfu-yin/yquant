"""Graded alerting with dedup + escalation (07 §5).

Severity ladder: S1 (data error may have hit decisions / books don't balance)
→ pinned banner + Feishu; S2 (degraded run / metric breach) → Feishu; S3
(observation only) → UI. Every alert binds a runbook section so it is
*actionable*. Same-source alerts dedupe inside a 4-hour window; an S3 that
repeats on three consecutive days auto-escalates to S2. Alerts are themselves
decision events (kind="alert"), so an alert storm is itself replayable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

Severity = Literal["S1", "S2", "S3"]

_DEDUP_WINDOW = timedelta(hours=4)
_ESCALATION_DAYS = 3

# v3.1 fixed alert sources (07 §5 ◆).
FIXED_SOURCES: dict[str, tuple[Severity, str]] = {
    "pillar_missing": ("S2", "runbook §6.2"),  # P10 支柱缺失
    "layer_budget_breach": ("S1", "runbook §6.3"),  # P11 层预算越界
    "regime_change": ("S3", "runbook §6.4"),  # 状态机切换 (Crisis 进入升 S1)
    "regime_change_crisis": ("S1", "runbook §6.4"),  # Crisis 进入
}


@dataclass(frozen=True)
class GradedAlert:
    source: str
    severity: Severity
    title: str
    text: str
    runbook: str
    ts: datetime
    escalated_from: Severity | None = None

    @property
    def channels(self) -> tuple[str, ...]:
        if self.severity == "S1":
            return ("banner", "feishu")
        if self.severity == "S2":
            return ("feishu",)
        return ("ui",)


@dataclass
class AlertRouter:
    """Stateful router applying dedup + escalation to a stream of alerts.

    State is kept in-process and deterministic given the timestamps handed in,
    so the escalation ladder is fully unit-testable without a wall clock.
    """

    _last_sent: dict[str, datetime] = field(default_factory=dict)
    _s3_days: dict[str, list[str]] = field(default_factory=dict)

    def route(
        self,
        *,
        source: str,
        title: str,
        text: str,
        ts: datetime,
        severity: Severity | None = None,
        runbook: str | None = None,
    ) -> GradedAlert | None:
        """Return the alert to deliver, or ``None`` when deduped inside the window."""

        moment = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
        resolved_sev, resolved_runbook = self._resolve(source, severity, runbook)

        escalated_from: Severity | None = None
        if resolved_sev == "S3" and self._maybe_escalate_s3(source, moment):
            escalated_from = "S3"
            resolved_sev = "S2"

        last = self._last_sent.get(source)
        if last is not None and moment - last < _DEDUP_WINDOW:
            return None
        self._last_sent[source] = moment

        return GradedAlert(
            source=source,
            severity=resolved_sev,
            title=title,
            text=text,
            runbook=resolved_runbook,
            ts=moment,
            escalated_from=escalated_from,
        )

    def _resolve(
        self, source: str, severity: Severity | None, runbook: str | None
    ) -> tuple[Severity, str]:
        if severity is not None:
            return severity, runbook or FIXED_SOURCES.get(source, (severity, "runbook §6.1"))[1]
        if source in FIXED_SOURCES:
            fixed_sev, fixed_runbook = FIXED_SOURCES[source]
            return fixed_sev, runbook or fixed_runbook
        return "S3", runbook or "runbook §6.1"

    def _maybe_escalate_s3(self, source: str, moment: datetime) -> bool:
        day = moment.date().isoformat()
        days = self._s3_days.setdefault(source, [])
        if day not in days:
            days.append(day)
        return _consecutive_tail(days) >= _ESCALATION_DAYS


def _consecutive_tail(days: list[str]) -> int:
    """Count trailing consecutive calendar days in an ordered ISO-date list."""

    if not days:
        return 0
    parsed = sorted({datetime.fromisoformat(d).date() for d in days})
    streak = 1
    for earlier, later in zip(parsed, parsed[1:], strict=False):
        if (later - earlier).days == 1:
            streak += 1
        else:
            streak = 1
    return streak
