"""Format M1 quality reports into alert messages.

Each formatter returns ``None`` when the report passed, so callers can route
uniformly: build the message, send only if it is not ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass

from yquant.datasrc.freshness import DailyBarFreshnessReport
from yquant.datasrc.reconcile import ReconciliationReport
from yquant.datasrc.reconcile_live import SampledLiveReconciliationReport


@dataclass(frozen=True)
class AlertMessage:
    title: str
    text: str


def freshness_alert(report: DailyBarFreshnessReport) -> AlertMessage | None:
    """Alert when any symbol is not fresh by the deadline."""

    if report.passed:
        return None
    stale = [item for item in report.items if item.status != "fresh"]
    lines = [
        f"- {item.symbol}: {item.status} ({item.detail})" for item in stale
    ]
    title = f"yquant freshness alert: {len(stale)} symbol(s) not fresh"
    text = "\n".join(
        [
            f"expected_date: {report.expected_date.isoformat()}",
            *lines,
        ]
    )
    return AlertMessage(title=title, text=text)


def reconcile_alert(report: ReconciliationReport) -> AlertMessage | None:
    """Alert when a stored-source reconciliation falls below its threshold."""

    if report.passed:
        return None
    title = (
        f"yquant reconciliation alert: {report.left_source} vs {report.right_source} "
        f"below threshold"
    )
    text = "\n".join(
        [
            f"compared_rows: {report.compared_rows}",
            f"mismatches: {len(report.mismatches)}",
            f"consistency_rate: {report.consistency_rate:.6f}",
            f"minimum_consistency_rate: {report.minimum_consistency_rate:.6f}",
            f"missing_left_rows: {report.missing_left_rows}",
            f"missing_right_rows: {report.missing_right_rows}",
        ]
    )
    return AlertMessage(title=title, text=text)


def live_reconcile_alert(report: SampledLiveReconciliationReport) -> AlertMessage | None:
    """Alert when a sampled live reconciliation fails or a source could not be fetched."""

    if report.passed:
        return None
    reconciliation = report.reconciliation
    title = (
        f"yquant live-reconciliation alert: {reconciliation.left_source} vs "
        f"{reconciliation.right_source}"
    )
    text = "\n".join(
        [
            f"sampled_symbols: {', '.join(report.sampled_symbols)}",
            f"left_fetch_failures: {report.left_fetch_failures}",
            f"right_fetch_failures: {report.right_fetch_failures}",
            f"compared_rows: {reconciliation.compared_rows}",
            f"mismatches: {len(reconciliation.mismatches)}",
            f"consistency_rate: {report.consistency_rate:.6f}",
        ]
    )
    return AlertMessage(title=title, text=text)
