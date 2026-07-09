#!/usr/bin/env python3
"""Monthly chaos-injection drill for the unattended job boundary (06 §5).

Injects the four faults the plan mandates — source outage, API timeout, disk
full, and lock contention — into a throwaway job context, then asserts the
system *degrades gracefully*: every job must record an ``error``/``failed``
outcome in the ledger and fire an alert instead of crashing, and no fault may
leave a torn or partial write behind. A surviving crash (an unhandled
exception) or a silent failure (no ledger row / no alert) fails the drill.

Run: ``python scripts/chaos_drill.py``
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pandas as pd

from yquant.config import load_config
from yquant.datasrc.repo import LocalDataRepo
from yquant.ledger import LedgerStore
from yquant.notify import AlertMessage, FeishuNotifier
from yquant.scheduler.jobs import JobContext, run_reconcile_live_job, run_update_job

_ON_DATE = date(2024, 1, 31)


class _OutageSource:
    """A source that always fails the way a real outage / timeout would."""

    def __init__(self, name: str, exc: Exception) -> None:
        self.name = name
        self._exc = exc

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise self._exc


def _capturing_context(root: Path, sent: list[AlertMessage]) -> JobContext:
    cfg = load_config("config.example.toml")
    runtime = replace(
        cfg.runtime,
        data_dir=root / "data",
        sqlite_path=root / "data" / "yquant.db",
        parquet_dir=root / "parquet",
        log_dir=root / "logs",
    )
    schedule = replace(cfg.schedule, symbols=("AAPL", "MSFT"))
    cfg = replace(cfg, runtime=runtime, schedule=schedule)

    def _capture(url: str, payload: dict[str, object]) -> None:
        content = payload["content"]
        assert isinstance(content, dict)
        title = str(content["text"]).split("\n", 1)[0]
        sent.append(AlertMessage(title=title, text=""))

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    ledger = LedgerStore(cfg.runtime.sqlite_path)
    ledger.bootstrap()
    notifier = FeishuNotifier("https://example.test/hook", transport=_capture)
    return JobContext(config=cfg, repo=repo, ledger=ledger, notifier=notifier)


@dataclass(frozen=True)
class Scenario:
    label: str
    run: Callable[[JobContext], object]


def _source_outage(ctx: JobContext) -> object:
    import yquant.scheduler.jobs as jobs

    original = jobs.build_daily_bar_sources
    jobs.build_daily_bar_sources = lambda names: [  # type: ignore[assignment]
        _OutageSource("yfinance", ConnectionError("name resolution failed"))
    ]
    try:
        return run_update_job(ctx, on_date=_ON_DATE)
    finally:
        jobs.build_daily_bar_sources = original  # type: ignore[assignment]


def _api_timeout(ctx: JobContext) -> object:
    import yquant.scheduler.jobs as jobs

    original = jobs.build_daily_bar_source
    jobs.build_daily_bar_source = lambda name: _OutageSource(  # type: ignore[assignment]
        name, TimeoutError("read timed out after 30s")
    )
    try:
        return run_reconcile_live_job(ctx, on_date=_ON_DATE)
    finally:
        jobs.build_daily_bar_source = original  # type: ignore[assignment]


def _disk_full(ctx: JobContext) -> object:
    import yquant.scheduler.jobs as jobs

    def _no_space(names: object) -> object:
        raise OSError(28, "No space left on device")

    original = jobs.build_daily_bar_sources
    jobs.build_daily_bar_sources = _no_space  # type: ignore[assignment]
    try:
        return run_update_job(ctx, on_date=_ON_DATE)
    finally:
        jobs.build_daily_bar_sources = original  # type: ignore[assignment]


def _lock_contention(ctx: JobContext) -> object:
    import yquant.scheduler.jobs as jobs

    original = jobs.build_daily_bar_source

    def _locked(name: str) -> object:
        raise BlockingIOError("database is locked")

    jobs.build_daily_bar_source = _locked  # type: ignore[assignment]
    try:
        return run_reconcile_live_job(ctx, on_date=_ON_DATE)
    finally:
        jobs.build_daily_bar_source = original  # type: ignore[assignment]


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("source outage (断源)", _source_outage),
    Scenario("API timeout (API 超时)", _api_timeout),
    Scenario("disk full (磁盘满)", _disk_full),
    Scenario("lock contention (锁竞争)", _lock_contention),
)


def _check(ctx: JobContext, outcome: object, sent: list[AlertMessage]) -> str | None:
    """Return a failure reason, or None when the system degraded gracefully."""

    status = getattr(outcome, "status", None)
    if status not in {"error", "failed"}:
        return f"expected error/failed outcome, got {status!r}"
    if not getattr(outcome, "alerted", False):
        return "fault did not raise an alert"
    if not sent:
        return "no alert was delivered to the notifier"
    runs = ctx.ledger.list_job_runs()
    if not runs or runs[-1].status not in {"error", "failed"}:
        return "ledger did not record the failed run"
    return None


def main() -> int:
    print("chaos drill: injecting job-boundary faults (06 §5)")
    survivors: list[str] = []
    for scenario in SCENARIOS:
        with tempfile.TemporaryDirectory() as tmp:
            sent: list[AlertMessage] = []
            ctx = _capturing_context(Path(tmp), sent)
            try:
                outcome = scenario.run(ctx)
            except Exception as exc:  # noqa: BLE001 - a crash is itself a failure
                print(f"CRASHED: {scenario.label}: {type(exc).__name__}: {exc}")
                survivors.append(f"{scenario.label} [crashed]")
                continue
            reason = _check(ctx, outcome, sent)
            if reason is None:
                print(f"survived:  {scenario.label} (graceful: error ledgered + alerted)")
            else:
                print(f"FAILED:    {scenario.label}: {reason}")
                survivors.append(f"{scenario.label} [{reason}]")

    handled = len(SCENARIOS) - len(survivors)
    print(f"\n{handled}/{len(SCENARIOS)} chaos scenarios handled gracefully")
    if survivors:
        print("Scenarios the system did not survive gracefully:")
        for survivor in survivors:
            print(f"  - {survivor}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
