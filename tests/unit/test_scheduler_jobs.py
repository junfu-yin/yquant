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
from yquant.risk.state_machine import RegimeConfig, RegimeInputs
from yquant.scheduler.jobs import (
    JobContext,
    build_job_context,
    build_scheduler,
    run_freshness_job,
    run_reconcile_live_job,
    run_regime_job,
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
        regime_cron=None,
    )
    ctx = _context(cfg)

    scheduler = build_scheduler(ctx)
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert job_ids == {"daily_bars_update", "daily_bars_freshness"}


# --- regime daily-ledger job (WP14 M9-L1 → M8 linkage) ---------------------


def _bearish_inputs() -> RegimeInputs:
    """Observables that drive every pillar to -1 (composite → Crisis)."""

    return RegimeInputs(
        spy_close=90.0,
        spy_ma_10m=100.0,
        pct_sectors_above_200d=0.20,
        hy_oas_percentile=0.90,
        hy_oas_change_3m_bp=200.0,
        hyg_lqd_z=-1.5,
        vix_level=35.0,
        vix_term_inversion_days=7,
        rsp_spy_trend_slope=-0.2,
        pct_above_200d=0.20,
        nfci=0.5,
        nfci_change=0.2,
        curve_10y_3m=-0.3,
        usd_change_3m=0.10,
    )


def test_regime_job_default_provider_starts_neutral_and_ledgers(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("SPY",))
    ctx = _context(cfg)

    outcome = run_regime_job(ctx, on_date=date(2024, 3, 1))

    assert outcome.status == "success"
    # No observables derived yet → all pillars stale, machine holds Neutral.
    assert outcome.detail["state"] == "Neutral"
    assert sorted(outcome.detail["stale_pillars"]) == sorted(RegimeConfig().weights)
    rows = ctx.ledger.list_regime_history()
    assert len(rows) == 1 and rows[0].state == "Neutral"
    assert ctx.ledger.list_job_runs()[-1].job == "macro_regime"


def test_regime_job_resumes_hysteresis_across_days(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("SPY",))
    ctx = _context(cfg)
    ctx.regime_config = RegimeConfig(confirm_periods=2)
    ctx.regime_inputs_provider = lambda repo, on: _bearish_inputs()

    # Day 1: Crisis is a candidate but hysteresis has not confirmed it yet.
    day1 = run_regime_job(ctx, on_date=date(2024, 3, 1))
    assert day1.detail["candidate"] == "Crisis"
    assert day1.detail["state"] == "Neutral"

    # Day 2: the second consecutive Crisis candidate commits the switch, proving
    # the pending streak was restored from day 1's ledgered memory snapshot.
    day2 = run_regime_job(ctx, on_date=date(2024, 3, 4))
    assert day2.detail["state"] == "Crisis"

    states = [row.state for row in ctx.ledger.list_regime_history()]
    assert states == ["Neutral", "Crisis"]


def test_regime_job_rerun_same_day_is_idempotent(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("SPY",))
    ctx = _context(cfg)
    ctx.regime_config = RegimeConfig(confirm_periods=1)
    ctx.regime_inputs_provider = lambda repo, on: _bearish_inputs()

    first = run_regime_job(ctx, on_date=date(2024, 3, 1))
    second = run_regime_job(ctx, on_date=date(2024, 3, 1))

    # Same date resumes from the prior day (none) both times → identical row.
    assert first.detail["state"] == second.detail["state"] == "Crisis"
    rows = ctx.ledger.list_regime_history()
    assert len(rows) == 1  # upsert, not duplicate


def test_regime_job_provider_error_is_recorded_and_alerted(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("SPY",))
    sent: list[AlertMessage] = []
    ctx = _context(cfg, sent=sent)

    def _boom(repo: LocalDataRepo, on: date) -> RegimeInputs:
        raise RuntimeError("adapter failed")

    ctx.regime_inputs_provider = _boom

    outcome = run_regime_job(ctx, on_date=date(2024, 3, 1))

    assert outcome.status == "error"
    assert outcome.alerted is True
    assert len(sent) == 1
    assert ctx.ledger.list_regime_history() == []
    assert ctx.ledger.list_job_runs()[-1].status == "error"


def test_regime_job_registered_when_cron_configured(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("SPY",), regime_cron="50 17 * * 1-5")
    ctx = _context(cfg)

    scheduler = build_scheduler(ctx)

    assert scheduler.get_job("macro_regime") is not None


def test_regime_job_falls_back_to_initial_on_legacy_row_without_memory(tmp_path: Path) -> None:
    cfg = _config(tmp_path, symbols=("SPY",))
    ctx = _context(cfg)
    # A prior row written before the memory snapshot existed (e.g. legacy schema).
    ctx.ledger.record_regime(
        as_of=date(2024, 3, 1), state="Neutral", composite=0.0, detail={"state": "Neutral"}
    )
    ctx.regime_config = RegimeConfig(confirm_periods=1)
    ctx.regime_inputs_provider = lambda repo, on: _bearish_inputs()

    outcome = run_regime_job(ctx, on_date=date(2024, 3, 4))

    # No usable memory snapshot → resume from initial Neutral, then evaluate today.
    assert outcome.status == "success"
    assert outcome.detail["state"] == "Crisis"
