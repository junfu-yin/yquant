"""Unattended M1 jobs: update, freshness, and sampled live reconciliation.

Each job runs the same tested logic the manual CLI uses, then records its
outcome in the ledger and fires a Feishu alert on failure. The functions take an
injectable :class:`JobContext` so they are unit-tested with fakes and no
network; :func:`build_scheduler` wires them onto APScheduler cron triggers.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from yquant.config import AppConfig
from yquant.datasrc.freshness import check_daily_bar_freshness, expected_daily_bar_deadline_utc
from yquant.datasrc.reconcile_live import run_sampled_live_reconciliation
from yquant.datasrc.repo import LocalDataRepo
from yquant.datasrc.retry import RetryPolicy
from yquant.datasrc.sources import build_daily_bar_source, build_daily_bar_sources
from yquant.datasrc.update import DailyBarsUpdater
from yquant.ledger import LedgerStore
from yquant.notify import notifier_from_env
from yquant.notify.alerts import AlertMessage, freshness_alert, live_reconcile_alert
from yquant.notify.feishu import FeishuNotifier, Transport
from yquant.risk.state_machine import RegimeConfig, RegimeInputs, RegimeMemory, step


class RegimeInputsProvider(Protocol):
    """Derives the M9 pillar observables for one date from a repo.

    This is the live-data seam between M1 storage and the pure state machine.
    Deriving the 14 observables (10-month MA, HY-OAS percentile, VIX term
    structure, NFCI, …) is a data-adapter task; until it lands, the default
    provider returns an all-``None`` :class:`RegimeInputs` so every pillar is
    stale and the machine carries forward rather than manufacturing a change
    (P10). Tests and the future adapter inject a real provider.
    """

    def __call__(self, repo: LocalDataRepo, on_date: date) -> RegimeInputs: ...


def _stale_regime_inputs(repo: LocalDataRepo, on_date: date) -> RegimeInputs:
    """Default provider: no derived observables yet → fully stale (P10)."""

    return RegimeInputs()


@dataclass(frozen=True)
class JobOutcome:
    job: str
    status: str  # success | failed | skipped | error
    detail: dict[str, Any]
    alerted: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"success", "skipped"}


@dataclass
class JobContext:
    config: AppConfig
    repo: LocalDataRepo
    ledger: LedgerStore
    notifier: FeishuNotifier | None
    retry_policy: RetryPolicy | None = None
    sleep: Callable[[float], None] = time.sleep
    regime_config: RegimeConfig = field(default_factory=RegimeConfig)
    regime_inputs_provider: RegimeInputsProvider = _stale_regime_inputs


def build_job_context(
    config: AppConfig,
    *,
    transport: Transport | None = None,
    retry_policy: RetryPolicy | None = None,
) -> JobContext:
    """Assemble a job context (repo, bootstrapped ledger, optional notifier)."""

    repo = LocalDataRepo(config.runtime.parquet_dir)
    ledger = LedgerStore(config.runtime.sqlite_path)
    ledger.bootstrap()
    notifier = notifier_from_env(config, transport=transport)
    return JobContext(
        config=config,
        repo=repo,
        ledger=ledger,
        notifier=notifier,
        retry_policy=retry_policy,
    )


def run_update_job(ctx: JobContext, *, on_date: date | None = None) -> JobOutcome:
    schedule = ctx.config.schedule
    symbols = list(schedule.symbols)
    on = on_date or date.today()
    start = on - timedelta(days=schedule.history_days)
    base_detail: dict[str, Any] = {
        "symbols": symbols,
        "start": start.isoformat(),
        "end": on.isoformat(),
    }
    if not symbols:
        return _finish(ctx, "daily_bars_update", "skipped", {"reason": "no symbols configured"})

    try:
        sources = build_daily_bar_sources(
            [ctx.config.data.primary_source, *ctx.config.data.backup_sources]
        )
        report = DailyBarsUpdater(
            ctx.repo,
            sources,
            retry_policy=ctx.retry_policy,
            sleep=ctx.sleep,
        ).update(symbols, start, on)
    except Exception as exc:  # noqa: BLE001 - job boundary records and alerts
        return _finish(
            ctx,
            "daily_bars_update",
            "error",
            {**base_detail, "error": _error_text(exc)},
            alert=_error_alert("update", exc),
        )

    status = "success" if report.passed else "failed"
    detail = {
        **base_detail,
        "succeeded_symbols": list(report.succeeded_symbols),
        "failed_symbols": list(report.failed_symbols),
    }
    alert = None
    if status != "success":
        alert = AlertMessage(
            title="yquant update alert: some symbols failed",
            text=f"failed_symbols: {', '.join(report.failed_symbols)}",
        )
    return _finish(ctx, "daily_bars_update", status, detail, alert=alert)


def run_freshness_job(ctx: JobContext, *, on_date: date | None = None) -> JobOutcome:
    schedule = ctx.config.schedule
    symbols = list(schedule.symbols)
    on = on_date or date.today()
    if not symbols:
        return _finish(ctx, "daily_bars_freshness", "skipped", {"reason": "no symbols configured"})

    deadline = None
    try:
        deadline = expected_daily_bar_deadline_utc(
            on,
            minutes_after_close=schedule.minutes_after_close,
            calendar_name=schedule.calendar,
        )
    except ValueError:
        # No calendar support or not a session; fall back to a date-only check.
        deadline = None

    report = check_daily_bar_freshness(
        ctx.repo,
        symbols,
        expected_date=on,
        deadline_utc=deadline,
    )
    status = "success" if report.passed else "failed"
    detail = {
        "expected_date": on.isoformat(),
        "statuses": {item.symbol: item.status for item in report.items},
    }
    return _finish(
        ctx,
        "daily_bars_freshness",
        status,
        detail,
        alert=freshness_alert(report),
    )


def run_reconcile_live_job(ctx: JobContext, *, on_date: date | None = None) -> JobOutcome:
    schedule = ctx.config.schedule
    symbols = list(schedule.symbols)
    on = on_date or date.today()
    start = on - timedelta(days=schedule.history_days)
    if not symbols:
        return _finish(
            ctx, "daily_bars_live_reconciliation", "skipped", {"reason": "no symbols configured"}
        )

    left_name = ctx.config.data.primary_source
    right_name = ctx.config.data.backup_sources[0] if ctx.config.data.backup_sources else "nasdaq"
    try:
        report = run_sampled_live_reconciliation(
            build_daily_bar_source(left_name),
            build_daily_bar_source(right_name),
            start=start,
            end=on,
            symbols=symbols,
            sample_size=schedule.reconcile_sample_size,
            seed=schedule.reconcile_seed,
            retry_policy=ctx.retry_policy,
        )
    except Exception as exc:  # noqa: BLE001 - job boundary records and alerts
        return _finish(
            ctx,
            "daily_bars_live_reconciliation",
            "error",
            {"error": _error_text(exc)},
            alert=_error_alert("live reconciliation", exc),
        )

    status = "success" if report.passed else "failed"
    detail = {
        "sampled_symbols": list(report.sampled_symbols),
        "consistency_rate": report.consistency_rate,
        "left_fetch_failures": report.left_fetch_failures,
        "right_fetch_failures": report.right_fetch_failures,
    }
    return _finish(
        ctx,
        "daily_bars_live_reconciliation",
        status,
        detail,
        alert=live_reconcile_alert(report),
    )


_REGIME_JOB = "macro_regime"
_REGIME_MEMORY_KEY = "memory"


def run_regime_job(ctx: JobContext, *, on_date: date | None = None) -> JobOutcome:
    """Step the M9 Layer-1 state machine one day and ledger the reading (WP14).

    Resumes hysteresis from the last ``regime_history`` row (its detail carries a
    ``memory`` snapshot), evaluates the injected inputs provider for ``on_date``,
    then upserts the day's reading. Re-running a date is idempotent: the machine
    resumes from the *prior* day, so the same inputs reproduce the same row (07).
    The committed state is what M8's ``apply_risk_controls`` consumes downstream.
    """

    on = on_date or date.today()
    try:
        memory = _load_regime_memory(ctx, before=on)
        inputs = ctx.regime_inputs_provider(ctx.repo, on)
        next_memory, reading = step(memory, inputs, ctx.regime_config)
        detail = reading.to_detail()
        detail[_REGIME_MEMORY_KEY] = next_memory.to_detail()
        ctx.ledger.record_regime(
            as_of=on,
            state=reading.state.value,
            composite=reading.composite,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001 - job boundary records and alerts
        return _finish(
            ctx,
            _REGIME_JOB,
            "error",
            {"as_of": on.isoformat(), "error": _error_text(exc)},
            alert=_error_alert("regime", exc),
        )

    return _finish(
        ctx,
        _REGIME_JOB,
        "success",
        {
            "as_of": on.isoformat(),
            "state": reading.state.value,
            "candidate": reading.candidate.value,
            "composite": round(reading.composite, 6),
            "stale_pillars": list(reading.stale_pillars),
        },
    )


def _load_regime_memory(ctx: JobContext, *, before: date) -> RegimeMemory:
    """Rebuild memory from the latest regime row strictly before ``before``.

    Rows on or after ``before`` are ignored so a same-day rerun resumes from the
    prior evaluation and stays idempotent. With no prior history the machine
    starts Neutral.
    """

    prior = [row for row in ctx.ledger.list_regime_history() if row.date < before]
    if not prior:
        return RegimeMemory.initial()
    snapshot = prior[-1].detail.get(_REGIME_MEMORY_KEY)
    if not isinstance(snapshot, dict):
        return RegimeMemory.initial()
    return RegimeMemory.from_detail(snapshot)


def build_scheduler(ctx: JobContext, *, scheduler: Any | None = None) -> Any:
    """Build an APScheduler configured with the cron jobs from ``ctx.config``.

    Returns the scheduler without starting it so callers control the run loop
    (and tests can inspect the registered jobs). APScheduler is imported lazily
    so the rest of this module has no hard scheduler dependency.
    """

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    timezone = ctx.config.runtime.timezone
    sched = scheduler if scheduler is not None else BlockingScheduler(timezone=timezone)
    schedule = ctx.config.schedule
    registrations = (
        ("daily_bars_update", schedule.update_cron, run_update_job),
        ("daily_bars_freshness", schedule.freshness_cron, run_freshness_job),
        ("daily_bars_live_reconciliation", schedule.reconcile_cron, run_reconcile_live_job),
        ("macro_regime", schedule.regime_cron, run_regime_job),
    )
    for job_id, cron, func in registrations:
        if not cron:
            continue
        sched.add_job(
            _job_runner(ctx, func),
            CronTrigger.from_crontab(cron, timezone=timezone),
            id=job_id,
            name=job_id,
            replace_existing=True,
        )
    return sched


def _job_runner(
    ctx: JobContext,
    func: Callable[..., JobOutcome],
) -> Callable[[], None]:
    def _run() -> None:
        func(ctx)

    return _run


def _finish(
    ctx: JobContext,
    job: str,
    status: str,
    detail: dict[str, Any],
    *,
    alert: AlertMessage | None = None,
) -> JobOutcome:
    ctx.ledger.record_job_run(job=job, status=status, detail=detail)
    alerted = False
    if alert is not None and ctx.notifier is not None:
        ctx.notifier.send(alert)
        alerted = True
    return JobOutcome(job=job, status=status, detail=detail, alerted=alerted)


def _error_alert(job_label: str, exc: BaseException) -> AlertMessage:
    return AlertMessage(
        title=f"yquant {job_label} job error",
        text=_error_text(exc),
    )


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"
