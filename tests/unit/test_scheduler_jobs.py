from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

import yquant.scheduler.jobs as jobs
from yquant.config import AppConfig, load_config
from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.repo import LocalDataRepo
from yquant.ledger import LedgerStore
from yquant.notify import AlertMessage, FeishuNotifier
from yquant.scheduler.jobs import (
    JobContext,
    build_job_context,
    build_scheduler,
    run_freshness_job,
    run_reconcile_live_job,
    run_update_job,
)


def _config(tmp_path: Path, **schedule_overrides: object) -> AppConfig:
    cfg = load_config("config.example.toml")
    runtime = replace(
        cfg.runtime,
        data_dir=tmp_path / "data",
        sqlite_path=tmp_path / "data" / "yquant.db",
        parquet_dir=tmp_path / "parquet",
        log_dir=tmp_path / "logs",
    )
    schedule = replace(cfg.schedule, **schedule_overrides)  # type: ignore[arg-type]
    return replace(cfg, runtime=runtime, schedule=schedule)


def _context(
    cfg: AppConfig,
    *,
    sent: list[AlertMessage] | None = None,
) -> JobContext:
    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    ledger = LedgerStore(cfg.runtime.sqlite_path)
    ledger.bootstrap()
    notifier = None
    if sent is not None:
        def _capture(url: str, payload: dict[str, object]) -> None:
            content = payload["content"]
            assert isinstance(content, dict)
            title = str(content["text"]).split("\n", 1)[0]
            sent.append(AlertMessage(title=title, text=""))

        notifier = FeishuNotifier("https://example.test/hook", transport=_capture)
    return JobContext(config=cfg, repo=repo, ledger=ledger, notifier=notifier)


def _bars(symbol: str) -> pd.DataFrame:
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-30", "2024-01-31"])),
        raw_open=pd.Series([99.0, 101.0]),
        raw_high=pd.Series([101.0, 103.0]),
        raw_low=pd.Series([98.0, 100.0]),
        raw_close=pd.Series([100.0, 102.0]),
        volume=pd.Series([1_000, 1_100]),
        source="yfinance",
        asof=datetime(2024, 1, 31, 21, 0, tzinfo=UTC),
    )


def test_update_job_skips_when_no_symbols(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=())
    ctx = _context(cfg)

    outcome = run_update_job(ctx, on_date=date(2024, 1, 31))

    assert outcome.status == "skipped"
    assert ctx.ledger.list_job_runs()[0].status == "skipped"


def test_freshness_job_success_is_ledgered_without_alert(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("AAPL",))
    sent: list[AlertMessage] = []
    ctx = _context(cfg, sent=sent)
    ctx.repo.write_daily_bars(_bars("AAPL"))

    outcome = run_freshness_job(ctx, on_date=date(2024, 1, 31))

    assert outcome.status == "success"
    assert outcome.alerted is False
    assert sent == []
    runs = ctx.ledger.list_job_runs()
    assert runs[-1].job == "daily_bars_freshness"
    assert runs[-1].status == "success"


def test_freshness_job_failure_alerts_and_ledgers(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("AAPL", "MSFT"))
    sent: list[AlertMessage] = []
    ctx = _context(cfg, sent=sent)
    ctx.repo.write_daily_bars(_bars("AAPL"))  # MSFT missing -> not fresh

    outcome = run_freshness_job(ctx, on_date=date(2024, 1, 31))

    assert outcome.status == "failed"
    assert outcome.alerted is True
    assert len(sent) == 1
    assert "freshness alert" in sent[0].title
    assert ctx.ledger.list_job_runs()[-1].status == "failed"


class _FakeSource:
    def __init__(self, name: str, frames: dict[str, pd.DataFrame], fail: bool = False) -> None:
        self.name = name
        self.frames = frames
        self.fail = fail

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if self.fail:
            raise RuntimeError("network down")
        return self.frames.get(symbol, pd.DataFrame())


def test_update_job_success_persists_and_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config(tmp_path, symbols=("AAPL",))
    ctx = _context(cfg)
    fake = _FakeSource("yfinance", {"AAPL": _bars("AAPL")})
    monkeypatch.setattr(jobs, "build_daily_bar_sources", lambda names: [fake])

    outcome = run_update_job(ctx, on_date=date(2024, 1, 31))

    assert outcome.status == "success"
    assert ctx.ledger.list_job_runs()[-1].job == "daily_bars_update"
    assert not ctx.repo.get_bars(["AAPL"], date(2024, 1, 1), date(2024, 1, 31)).empty


def test_update_job_error_is_recorded_and_alerted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config(tmp_path, symbols=("AAPL",))
    sent: list[AlertMessage] = []
    ctx = _context(cfg, sent=sent)

    def _boom(names: list[str]) -> list[object]:
        raise RuntimeError("source factory failed")

    monkeypatch.setattr(jobs, "build_daily_bar_sources", _boom)

    outcome = run_update_job(ctx, on_date=date(2024, 1, 31))

    assert outcome.status == "error"
    assert outcome.alerted is True
    assert len(sent) == 1
    assert ctx.ledger.list_job_runs()[-1].status == "error"


def test_reconcile_live_job_records_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config(tmp_path, symbols=("AAPL",), reconcile_sample_size=1, reconcile_seed=1)
    ctx = _context(cfg)
    sources = {
        "yfinance": _FakeSource("yfinance", {"AAPL": _bars("AAPL")}),
        "stooq": _FakeSource("stooq", {"AAPL": _bars("AAPL")}),
    }
    monkeypatch.setattr(jobs, "build_daily_bar_source", lambda name: sources[name])

    outcome = run_reconcile_live_job(ctx, on_date=date(2024, 1, 31))

    assert outcome.status == "success"
    assert ctx.ledger.list_job_runs()[-1].job == "daily_bars_live_reconciliation"


def test_reconcile_live_job_error_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(tmp_path, symbols=("AAPL",))
    ctx = _context(cfg)

    def _boom(name: str) -> object:
        raise RuntimeError("bad source")

    monkeypatch.setattr(jobs, "build_daily_bar_source", _boom)

    outcome = run_reconcile_live_job(ctx, on_date=date(2024, 1, 31))
    assert outcome.status == "error"


def test_build_job_context_bootstraps_ledger(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("AAPL",))
    ctx = build_job_context(cfg)
    assert ctx.notifier is None  # no webhook env set
    assert ctx.ledger.list_job_runs() == []


def test_scheduler_job_runner_invokes_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config(tmp_path, symbols=("AAPL",), freshness_cron="45 17 * * 1-5")
    ctx = _context(cfg)
    ctx.repo.write_daily_bars(_bars("AAPL"))

    scheduler = build_scheduler(ctx)
    job = scheduler.get_job("daily_bars_freshness")
    job.func()  # exercise the _job_runner closure

    assert ctx.ledger.list_job_runs()[-1].job == "daily_bars_freshness"


def test_build_scheduler_registers_only_configured_crons(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        symbols=("AAPL",),
        update_cron="30 17 * * 1-5",
        freshness_cron="45 17 * * 1-5",
        reconcile_cron=None,
    )
    ctx = _context(cfg)

    scheduler = build_scheduler(ctx)
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert job_ids == {"daily_bars_update", "daily_bars_freshness"}
