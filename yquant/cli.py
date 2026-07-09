"""Command line interface for local development and operations."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from yquant.config import ConfigError, load_config
from yquant.datasrc import (
    DailyBarsUpdater,
    LocalDataRepo,
    check_daily_bar_freshness,
    expected_daily_bar_deadline_utc,
    reconcile_daily_bars,
    run_sampled_live_reconciliation,
    write_report_artifact,
)
from yquant.datasrc.bars import normalize_symbols
from yquant.datasrc.protocols import DailyBarSource
from yquant.datasrc.sources import build_daily_bar_source, build_daily_bar_sources
from yquant.probes.calendar import run_calendar_probe
from yquant.probes.edgar import run_edgar_probe
from yquant.probes.models import CheckResult, ProbeRun, make_probe_run, utc_now_iso, write_probe_run
from yquant.probes.stooq import run_stooq_probe
from yquant.probes.yfinance_probe import run_yfinance_probe
from yquant.scheduler.jobs import (
    JobContext,
    JobOutcome,
    build_job_context,
    build_scheduler,
    run_freshness_job,
    run_reconcile_live_job,
    run_update_job,
)
from yquant.version import __version__

if TYPE_CHECKING:
    from yquant.backtest import TargetProvider
    from yquant.risk.state_machine import RegimeReading
    from yquant.strategies.base import TargetPortfolio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yquant", description="yquant local toolkit")
    parser.add_argument("--version", action="version", version=f"yquant {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=False)

    doctor = subparsers.add_parser("doctor", help="inspect runtime and configuration")
    doctor.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to inspect",
    )

    data = subparsers.add_parser("data", help="run M1 data jobs")
    data_subparsers = data.add_subparsers(dest="data_command", required=True)
    data_update = data_subparsers.add_parser("update", help="fetch and persist daily bars")
    data_update.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_update.add_argument(
        "--symbols",
        required=True,
        help="comma-separated US tickers, e.g. AAPL,MSFT,SPY",
    )
    data_update.add_argument("--start", required=True, help="inclusive start date, YYYY-MM-DD")
    data_update.add_argument("--end", required=True, help="inclusive end date, YYYY-MM-DD")
    data_update.add_argument(
        "--quality-dir",
        type=Path,
        default=None,
        help="directory for update quality artifacts; defaults to data_dir/quality",
    )

    data_freshness = data_subparsers.add_parser(
        "freshness",
        help="check local daily-bar freshness for an expected session",
    )
    data_freshness.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_freshness.add_argument(
        "--symbols",
        required=True,
        help="comma-separated US tickers, e.g. AAPL,MSFT,SPY",
    )
    data_freshness.add_argument(
        "--expected-date",
        required=True,
        help="expected bar date, YYYY-MM-DD",
    )
    data_freshness.add_argument(
        "--deadline-utc",
        default=None,
        help="optional freshness deadline in UTC ISO format",
    )
    data_freshness.add_argument(
        "--use-calendar-deadline",
        action="store_true",
        help="derive deadline from the exchange close plus --minutes-after-close",
    )
    data_freshness.add_argument(
        "--minutes-after-close",
        type=int,
        default=45,
        help="minutes after exchange close for calendar-derived freshness deadline",
    )
    data_freshness.add_argument(
        "--calendar",
        default="NYSE",
        help="pandas_market_calendars calendar name for deadline derivation",
    )
    data_freshness.add_argument(
        "--lookback-days",
        type=int,
        default=10,
        help="days to search backward when reporting stale data",
    )
    data_freshness.add_argument(
        "--quality-dir",
        type=Path,
        default=None,
        help="directory for freshness artifacts; defaults to data_dir/quality",
    )

    data_reconcile = data_subparsers.add_parser(
        "reconcile",
        help="compare persisted daily bars across two sources",
    )
    data_reconcile.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_reconcile.add_argument("--symbols", required=True, help="comma-separated tickers")
    data_reconcile.add_argument("--start", required=True, help="inclusive start date, YYYY-MM-DD")
    data_reconcile.add_argument("--end", required=True, help="inclusive end date, YYYY-MM-DD")
    data_reconcile.add_argument("--left-source", default="yfinance")
    data_reconcile.add_argument("--right-source", default="stooq")
    data_reconcile.add_argument("--price-column", default="close_raw")
    data_reconcile.add_argument("--tolerance-bps", type=float, default=10.0)
    data_reconcile.add_argument("--minimum-consistency-rate", type=float, default=0.995)
    data_reconcile.add_argument(
        "--quality-dir",
        type=Path,
        default=None,
        help="directory for reconciliation artifacts; defaults to data_dir/quality",
    )

    data_reconcile_live = data_subparsers.add_parser(
        "reconcile-live",
        help="sample symbols, fetch both sources live, and reconcile",
    )
    data_reconcile_live.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_reconcile_live.add_argument(
        "--symbols",
        default=None,
        help="comma-separated ticker pool to sample; defaults to the repo universe",
    )
    data_reconcile_live.add_argument("--start", required=True, help="inclusive start, YYYY-MM-DD")
    data_reconcile_live.add_argument("--end", required=True, help="inclusive end, YYYY-MM-DD")
    data_reconcile_live.add_argument(
        "--on-date",
        default=None,
        help="universe as-of date when sampling from the repo; defaults to --end",
    )
    data_reconcile_live.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="number of symbols to sample; defaults to the whole pool",
    )
    data_reconcile_live.add_argument(
        "--seed",
        type=int,
        default=None,
        help="random seed for reproducible sampling evidence",
    )
    data_reconcile_live.add_argument("--left-source", default="yfinance")
    data_reconcile_live.add_argument("--right-source", default="stooq")
    data_reconcile_live.add_argument("--price-column", default="close_raw")
    data_reconcile_live.add_argument("--tolerance-bps", type=float, default=10.0)
    data_reconcile_live.add_argument("--minimum-consistency-rate", type=float, default=0.995)
    data_reconcile_live.add_argument(
        "--request-pause-seconds",
        type=float,
        default=0.0,
        help="pause between symbols to stay within source rate limits",
    )
    data_reconcile_live.add_argument(
        "--quality-dir",
        type=Path,
        default=None,
        help="directory for live reconciliation artifacts; defaults to data_dir/quality",
    )

    data_load_securities = data_subparsers.add_parser(
        "load-securities",
        help="load a survivorship-safe security master from a CSV",
    )
    data_load_securities.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_load_securities.add_argument(
        "--csv",
        required=True,
        type=Path,
        help="CSV with columns symbol,market,listing_date[,delisting_date]",
    )

    data_universe = data_subparsers.add_parser(
        "universe",
        help="print the point-in-time tradable universe on a date",
    )
    data_universe.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_universe.add_argument(
        "--on-date",
        required=True,
        help="as-of session date, YYYY-MM-DD",
    )
    data_universe.add_argument(
        "--market",
        default="all",
        choices=["us", "all"],
        help="restrict to a market or 'all'",
    )

    data_update_macro = data_subparsers.add_parser(
        "update-macro",
        help="fetch and persist macro/index level series",
    )
    data_update_macro.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_update_macro.add_argument(
        "--series",
        required=True,
        help="comma-separated series ids, e.g. ^GSPC,^VIX",
    )
    data_update_macro.add_argument("--start", required=True, help="inclusive start, YYYY-MM-DD")
    data_update_macro.add_argument("--end", required=True, help="inclusive end, YYYY-MM-DD")

    data_asof = data_subparsers.add_parser(
        "asof",
        help="read bars as known at a point in time (replay lookahead guard)",
    )
    data_asof.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    data_asof.add_argument(
        "--symbols", default=None, help="comma-separated tickers (daily bars)"
    )
    data_asof.add_argument(
        "--series",
        default=None,
        help="comma-separated macro series ids, e.g. ^VIX,BAMLH0A0HYM2 (07 §3)",
    )
    data_asof.add_argument("--start", required=True, help="inclusive start, YYYY-MM-DD")
    data_asof.add_argument("--end", required=True, help="inclusive end, YYYY-MM-DD")
    data_asof.add_argument(
        "--as-of-utc",
        required=True,
        help="point-in-time cutoff in UTC ISO format, e.g. 2024-02-01T00:45:00Z",
    )
    data_asof.add_argument(
        "--adjust",
        default="adjusted",
        choices=["none", "adjusted"],
        help="price adjustment view",
    )

    schedule = subparsers.add_parser("schedule", help="run unattended M1 jobs")
    schedule_subparsers = schedule.add_subparsers(dest="schedule_command", required=True)

    def add_schedule_config(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--config",
            type=Path,
            default=Path("config.example.toml"),
            help="config file to use",
        )

    schedule_list = schedule_subparsers.add_parser(
        "list", help="show configured cron jobs and symbols"
    )
    add_schedule_config(schedule_list)

    schedule_run_once = schedule_subparsers.add_parser(
        "run-once", help="run one job immediately and record its outcome"
    )
    add_schedule_config(schedule_run_once)
    schedule_run_once.add_argument(
        "--job",
        required=True,
        choices=["update", "freshness", "reconcile-live"],
        help="which job to run now",
    )
    schedule_run_once.add_argument(
        "--on-date",
        default=None,
        help="session date, YYYY-MM-DD; defaults to today",
    )

    schedule_run = schedule_subparsers.add_parser(
        "run", help="start the blocking scheduler daemon"
    )
    add_schedule_config(schedule_run)

    probe = subparsers.add_parser("probe", help="run WP0 assumption probes")
    probe_subparsers = probe.add_subparsers(dest="probe_name", required=True)

    def add_output_dir(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--output-dir",
            type=Path,
            default=Path("data/probes"),
            help="directory for JSON probe evidence",
        )

    yfinance = probe_subparsers.add_parser("yfinance", help="probe yfinance (primary US bars)")
    yfinance.add_argument("--us-symbol", default="AAPL", help="US ticker for sample bar fetch")
    yfinance.add_argument("--index-symbol", default="^GSPC", help="index symbol for sample fetch")
    add_output_dir(yfinance)

    stooq = probe_subparsers.add_parser("stooq", help="probe Stooq (backup US/index bars)")
    stooq.add_argument("--us-symbol", default="AAPL", help="US symbol for sample bar fetch")
    stooq.add_argument("--index-symbol", default="^SPX", help="index symbol for sample fetch")
    add_output_dir(stooq)

    edgar = probe_subparsers.add_parser("edgar", help="probe SEC EDGAR (US announcements)")
    edgar.add_argument("--symbol", default="AAPL", help="US ticker for filing lookup")
    edgar.add_argument(
        "--user-agent-env",
        default="YQUANT_SEC_USER_AGENT",
        help="env var holding the SEC fair-access User-Agent",
    )
    add_output_dir(edgar)

    calendar = probe_subparsers.add_parser("calendar", help="probe pandas_market_calendars")
    calendar.add_argument("--start", default="2024-01-01", help="schedule start date")
    calendar.add_argument("--end", default="2024-01-31", help="schedule end date")
    add_output_dir(calendar)

    all_sources = probe_subparsers.add_parser("all", help="probe all configured data sources")
    all_sources.add_argument("--us-symbol", default="AAPL")
    all_sources.add_argument("--index-symbol", default="^GSPC")
    all_sources.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="timeout for each source probe subprocess",
    )
    add_output_dir(all_sources)

    backtest = subparsers.add_parser(
        "backtest",
        help="run an M2 deterministic backtest and emit the report",
    )
    backtest.add_argument(
        "--config",
        type=Path,
        default=Path("config.example.toml"),
        help="config file to use",
    )
    backtest.add_argument(
        "--symbols",
        required=True,
        help="comma-separated tickers to hold, e.g. SPY,QQQ",
    )
    backtest.add_argument(
        "--weights",
        default=None,
        help="comma-separated target weights matching --symbols; defaults to equal weight",
    )
    backtest.add_argument("--start", required=True, help="inclusive start date, YYYY-MM-DD")
    backtest.add_argument("--end", required=True, help="inclusive end date, YYYY-MM-DD")
    backtest.add_argument(
        "--initial-cash",
        type=float,
        default=100_000.0,
        help="starting cash in USD",
    )
    backtest.add_argument(
        "--benchmark",
        default="SPY",
        help="buy-and-hold benchmark symbol for the report comparison",
    )
    backtest.add_argument(
        "--single-stocks",
        default=None,
        help="comma-separated subset of --symbols priced with the single-stock slippage tier",
    )
    backtest.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional path to write the JSON report artifact",
    )

    qa = subparsers.add_parser("qa", help="run scriptable P-metric quality gates (06)")
    qa_subparsers = qa.add_subparsers(dest="qa_command", required=True)

    qa_golden = qa_subparsers.add_parser(
        "golden", help="print frozen golden-window content hashes and manifests (06 §4)"
    )
    qa_golden.add_argument(
        "--window",
        default="all",
        help="golden window key (e.g. 2020_covid) or 'all'",
    )

    qa_panel = qa_subparsers.add_parser(
        "panel", help="run the P-metric panel over a golden window and print the board (06 §8)"
    )
    qa_panel.add_argument(
        "--window",
        default="2020_covid",
        help="golden window key to drive the panel",
    )
    qa_panel.add_argument(
        "--initial-cash",
        type=float,
        default=50_000.0,
        help="starting cash for the panel backtest, in USD",
    )
    qa_panel.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional path to write the JSON panel artifact",
    )

    qa_drills = qa_subparsers.add_parser(
        "drills",
        help="run the drill台账: four historical-event replays + a fire drill (06 §5)",
    )
    qa_drills.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional path to write the JSON drill ledger",
    )

    ledger = subparsers.add_parser("ledger", help="inspect the decision-event ledger (07)")
    ledger_subparsers = ledger.add_subparsers(dest="ledger_command", required=True)

    ledger_replay = ledger_subparsers.add_parser(
        "replay", help="recompute and verify a run digest (07 §4)"
    )
    ledger_replay.add_argument(
        "--config", type=Path, default=Path("config.example.toml"), help="config file to use"
    )
    ledger_replay.add_argument("--run-id", required=True, help="run id to replay")
    ledger_replay.add_argument(
        "--strict",
        action="store_true",
        help="fail (exit 1) on any digest mismatch or provenance drift",
    )

    ledger_incident = ledger_subparsers.add_parser(
        "collect", help="collect an incident evidence bundle for a run (07 §6)"
    )
    ledger_incident.add_argument(
        "--config", type=Path, default=Path("config.example.toml"), help="config file to use"
    )
    ledger_incident.add_argument("--run-id", required=True, help="run id under investigation")
    ledger_incident.add_argument(
        "--output", type=Path, default=None, help="optional path to write the JSON evidence bundle"
    )

    ledger_chain = ledger_subparsers.add_parser(
        "chain", help="show the causal chain leading to an event (07 §2)"
    )
    ledger_chain.add_argument(
        "--config", type=Path, default=Path("config.example.toml"), help="config file to use"
    )
    ledger_chain.add_argument("--event-id", required=True, help="leaf event id to trace back")

    return parser


def _doctor(config_path: Path) -> int:
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    llm_key_present = bool(os.getenv(cfg.llm.api_key_env))
    feishu_present = bool(os.getenv(cfg.notification.feishu.webhook_env))

    print(f"yquant: {__version__}")
    print(f"config: {config_path}")
    print(f"timezone: {cfg.runtime.timezone}")
    print(f"data_dir: {cfg.runtime.data_dir}")
    print(f"sqlite_path: {cfg.runtime.sqlite_path}")
    print(f"markets: {', '.join(cfg.data.markets)}")
    print(f"primary_source: {cfg.data.primary_source}")
    print(f"backup_sources: {', '.join(cfg.data.backup_sources)}")
    print(f"llm_provider: {cfg.llm.provider}")
    print(f"llm_model: {cfg.llm.model}")
    print(f"llm_api_key_env_present: {llm_key_present}")
    print(f"feishu_webhook_env_present: {feishu_present}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _doctor(args.config)
    if args.command == "data":
        return _run_data(args)
    if args.command == "schedule":
        return _run_schedule(args)
    if args.command == "probe":
        return _run_probe(args)
    if args.command == "backtest":
        return _run_backtest(args)
    if args.command == "qa":
        return _run_qa(args)
    if args.command == "ledger":
        return _run_ledger(args)

    parser.print_help()
    return 0


def _run_data(args: argparse.Namespace) -> int:
    if args.data_command == "update":
        return _run_data_update(args)
    if args.data_command == "freshness":
        return _run_data_freshness(args)
    if args.data_command == "reconcile":
        return _run_data_reconcile(args)
    if args.data_command == "reconcile-live":
        return _run_data_reconcile_live(args)
    if args.data_command == "load-securities":
        return _run_data_load_securities(args)
    if args.data_command == "universe":
        return _run_data_universe(args)
    if args.data_command == "update-macro":
        return _run_data_update_macro(args)
    if args.data_command == "asof":
        return _run_data_asof(args)
    return 0


def _run_data_update(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        symbols = normalize_symbols(_split_symbols(args.symbols))
        if not symbols:
            raise ValueError("--symbols must include at least one ticker")
        sources = _daily_bar_sources([cfg.data.primary_source, *cfg.data.backup_sources])
    except (ConfigError, ValueError) as exc:
        print(f"data update error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    report = DailyBarsUpdater(repo, sources).update(symbols, start, end)
    artifact_path = write_report_artifact(
        report,
        _quality_output_dir(cfg.runtime.data_dir, args.quality_dir),
        kind="daily_bars_update",
    )
    print("data_update: daily_bars")
    print(f"symbols: {', '.join(report.symbols)}")
    print(f"range: {report.start.isoformat()}..{report.end.isoformat()}")
    for attempt in report.attempts:
        print(f"- {attempt.symbol} {attempt.source}: {attempt.status} rows={attempt.row_count}")
        if attempt.error:
            print(f"  error: {attempt.error}")
        for issue in attempt.quality_issues:
            print(f"  quality: {issue}")
    for manifest in report.manifests:
        print(f"manifest: {manifest.manifest_id}")
        print(f"storage: {manifest.storage_path}")
    print(f"quality_artifact: {artifact_path}")
    if report.failed_symbols:
        print(f"failed_symbols: {', '.join(report.failed_symbols)}", file=sys.stderr)
        return 1
    return 0


def _run_data_freshness(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        expected_date = date.fromisoformat(args.expected_date)
        deadline = _freshness_deadline(args, expected_date)
        symbols = normalize_symbols(_split_symbols(args.symbols))
        if not symbols:
            raise ValueError("--symbols must include at least one ticker")
        if args.lookback_days < 0:
            raise ValueError("--lookback-days must be non-negative")
    except (ConfigError, ValueError) as exc:
        print(f"data freshness error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    report = check_daily_bar_freshness(
        repo,
        symbols,
        expected_date=expected_date,
        deadline_utc=deadline,
        lookback_days=args.lookback_days,
    )
    artifact_path = write_report_artifact(
        report,
        _quality_output_dir(cfg.runtime.data_dir, args.quality_dir),
        kind="daily_bars_freshness",
    )
    print("data_freshness: daily_bars")
    print(f"expected_date: {report.expected_date.isoformat()}")
    if report.deadline_utc is not None:
        print(f"deadline_utc: {report.deadline_utc.isoformat()}")
    for item in report.items:
        latest_date = item.latest_date.isoformat() if item.latest_date is not None else "none"
        latest_asof = (
            item.latest_asof_utc.isoformat() if item.latest_asof_utc is not None else "none"
        )
        print(
            f"- {item.symbol}: {item.status} "
            f"latest_date={latest_date} latest_asof_utc={latest_asof}"
        )
        print(f"  detail: {item.detail}")
    print(f"quality_artifact: {artifact_path}")
    return 0 if report.passed else 1


def _run_data_reconcile(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        symbols = normalize_symbols(_split_symbols(args.symbols))
        if not symbols:
            raise ValueError("--symbols must include at least one ticker")
    except (ConfigError, ValueError) as exc:
        print(f"data reconcile error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    left = repo.get_daily_bars_storage(
        symbols,
        start,
        end,
        sources=[args.left_source],
    )
    right = repo.get_daily_bars_storage(
        symbols,
        start,
        end,
        sources=[args.right_source],
    )
    try:
        report = reconcile_daily_bars(
            left,
            right,
            left_source=args.left_source,
            right_source=args.right_source,
            price_column=args.price_column,
            tolerance_bps=args.tolerance_bps,
            minimum_consistency_rate=args.minimum_consistency_rate,
        )
    except ValueError as exc:
        print(f"data reconcile error: {exc}", file=sys.stderr)
        return 2

    artifact_path = write_report_artifact(
        report,
        _quality_output_dir(cfg.runtime.data_dir, args.quality_dir),
        kind="daily_bars_reconciliation",
    )
    print("data_reconcile: daily_bars")
    print(f"symbols: {', '.join(symbols)}")
    print(f"range: {start.isoformat()}..{end.isoformat()}")
    print(f"sources: {report.left_source} vs {report.right_source}")
    print(f"compared_rows: {report.compared_rows}")
    print(f"missing_left_rows: {report.missing_left_rows}")
    print(f"missing_right_rows: {report.missing_right_rows}")
    print(f"mismatches: {len(report.mismatches)}")
    print(f"consistency_rate: {report.consistency_rate:.6f}")
    print(f"quality_artifact: {artifact_path}")
    return 0 if report.passed else 1


def _run_data_reconcile_live(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        on_date = date.fromisoformat(args.on_date) if args.on_date else None
        symbols = normalize_symbols(_split_symbols(args.symbols)) if args.symbols else None
        left_source = _daily_bar_source(args.left_source)
        right_source = _daily_bar_source(args.right_source)
    except (ConfigError, ValueError) as exc:
        print(f"data reconcile-live error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    try:
        report = run_sampled_live_reconciliation(
            left_source,
            right_source,
            start=start,
            end=end,
            symbols=symbols,
            repo=repo,
            on_date=on_date,
            sample_size=args.sample_size,
            seed=args.seed,
            price_column=args.price_column,
            tolerance_bps=args.tolerance_bps,
            minimum_consistency_rate=args.minimum_consistency_rate,
            request_pause_seconds=args.request_pause_seconds,
        )
    except ValueError as exc:
        print(f"data reconcile-live error: {exc}", file=sys.stderr)
        return 2

    artifact_path = write_report_artifact(
        report,
        _quality_output_dir(cfg.runtime.data_dir, args.quality_dir),
        kind="daily_bars_live_reconciliation",
    )
    reconciliation = report.reconciliation
    print("data_reconcile_live: daily_bars")
    print(f"range: {start.isoformat()}..{end.isoformat()}")
    print(f"sources: {reconciliation.left_source} vs {reconciliation.right_source}")
    print(f"universe_size: {report.universe_size}")
    print(f"sample_size: {report.sample_size} seed: {report.seed}")
    print(f"sampled_symbols: {', '.join(report.sampled_symbols)}")
    print(f"left_fetch_failures: {report.left_fetch_failures}")
    print(f"right_fetch_failures: {report.right_fetch_failures}")
    print(f"compared_rows: {reconciliation.compared_rows}")
    print(f"missing_left_rows: {reconciliation.missing_left_rows}")
    print(f"missing_right_rows: {reconciliation.missing_right_rows}")
    print(f"mismatches: {len(reconciliation.mismatches)}")
    print(f"consistency_rate: {report.consistency_rate:.6f}")
    print(f"quality_artifact: {artifact_path}")
    return 0 if report.passed else 1


def _run_data_load_securities(args: argparse.Namespace) -> int:
    import pandas as pd

    try:
        cfg = load_config(args.config)
        if not args.csv.exists():
            raise ValueError(f"security master CSV does not exist: {args.csv}")
        frame = pd.read_csv(args.csv)
    except (ConfigError, ValueError) as exc:
        print(f"data load-securities error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    try:
        master = repo.write_security_master(frame)
    except ValueError as exc:
        print(f"data load-securities error: {exc}", file=sys.stderr)
        return 2
    print("data_load_securities: security_master")
    print(f"rows: {len(master)}")
    print(f"storage: {repo.security_master_path}")
    return 0


def _run_data_universe(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        on_date = date.fromisoformat(args.on_date)
    except (ConfigError, ValueError) as exc:
        print(f"data universe error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    symbols = repo.get_universe(on_date, args.market)
    source = "security_master" if not repo.get_security_master().empty else "bar_presence"
    print("data_universe: tradable universe")
    print(f"on_date: {on_date.isoformat()}")
    print(f"market: {args.market}")
    print(f"source: {source}")
    print(f"count: {len(symbols)}")
    print(f"symbols: {', '.join(symbols) if symbols else '(none)'}")
    return 0


def _run_data_asof(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        as_of = _parse_deadline_utc(args.as_of_utc)
        if as_of is None:
            raise ValueError("--as-of-utc must be a UTC ISO timestamp")
        series_ids = _split_symbols(args.series) if args.series else []
        symbols = normalize_symbols(_split_symbols(args.symbols)) if args.symbols else []
        if not symbols and not series_ids:
            raise ValueError("provide --symbols and/or --series")
    except (ConfigError, ValueError) as exc:
        print(f"data asof error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    print("data_asof")
    print(f"as_of_utc: {as_of.isoformat()}")
    print(f"range: {start.isoformat()}..{end.isoformat()}")

    if symbols:
        bars = repo.get_bars_asof(symbols, start, end, as_of, args.adjust)
        print(f"daily_bars_rows: {len(bars)}")
        if not bars.empty:
            latest = bars.groupby("symbol")["date"].max()
            for symbol in symbols:
                latest_date = latest.get(symbol)
                shown = latest_date.isoformat() if latest_date is not None else "(none)"
                print(f"- {symbol}: latest_visible_date={shown}")

    if series_ids:
        macro = repo.get_macro_series_asof(series_ids, start, end, as_of)
        print(f"macro_series_rows: {len(macro)}")
        if not macro.empty:
            latest = macro.groupby("series_id")["date"].max()
            for series_id in {s.strip().upper() for s in series_ids}:
                latest_date = latest.get(series_id)
                shown = latest_date.isoformat() if latest_date is not None else "(none)"
                print(f"- {series_id}: latest_visible_date={shown}")
    return 0


def _run_data_update_macro(args: argparse.Namespace) -> int:
    from yquant.datasrc.macro import MacroUpdater, YFinanceMacroSource

    try:
        cfg = load_config(args.config)
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        series_ids = _split_symbols(args.series)
        if not series_ids:
            raise ValueError("--series must include at least one series id")
    except (ConfigError, ValueError) as exc:
        print(f"data update-macro error: {exc}", file=sys.stderr)
        return 2

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    report = MacroUpdater(repo, YFinanceMacroSource()).update(series_ids, start, end)
    print("data_update_macro: macro_series")
    print(f"series: {', '.join(report.series_ids)}")
    print(f"range: {report.start.isoformat()}..{report.end.isoformat()}")
    for attempt in report.attempts:
        print(f"- {attempt.series_id} {attempt.source}: {attempt.status} rows={attempt.row_count}")
        if attempt.error:
            print(f"  error: {attempt.error}")
    if report.failed_series:
        print(f"failed_series: {', '.join(report.failed_series)}", file=sys.stderr)
        return 1
    return 0


def _run_schedule(args: argparse.Namespace) -> int:
    if args.schedule_command == "list":
        return _run_schedule_list(args)
    if args.schedule_command == "run-once":
        return _run_schedule_run_once(args)
    if args.schedule_command == "run":
        return _run_schedule_run(args)
    return 0


def _run_schedule_list(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"schedule list error: {exc}", file=sys.stderr)
        return 2

    schedule = cfg.schedule
    print("schedule: configured jobs")
    print(f"timezone: {cfg.runtime.timezone}")
    print(f"symbols: {', '.join(schedule.symbols) if schedule.symbols else '(none)'}")
    print(f"history_days: {schedule.history_days}")
    print(f"update_cron: {schedule.update_cron or '(disabled)'}")
    print(f"freshness_cron: {schedule.freshness_cron or '(disabled)'}")
    print(f"reconcile_cron: {schedule.reconcile_cron or '(disabled)'}")
    print(f"reconcile_sample_size: {schedule.reconcile_sample_size}")
    print(f"reconcile_seed: {schedule.reconcile_seed}")
    return 0


def _run_schedule_run_once(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        on_date = date.fromisoformat(args.on_date) if args.on_date else None
    except (ConfigError, ValueError) as exc:
        print(f"schedule run-once error: {exc}", file=sys.stderr)
        return 2

    ctx = build_job_context(cfg)
    runners: dict[str, Callable[[JobContext], JobOutcome]] = {
        "update": lambda c: run_update_job(c, on_date=on_date),
        "freshness": lambda c: run_freshness_job(c, on_date=on_date),
        "reconcile-live": lambda c: run_reconcile_live_job(c, on_date=on_date),
    }
    outcome = runners[args.job](ctx)
    print(f"schedule_run_once: {outcome.job}")
    print(f"status: {outcome.status}")
    print(f"alerted: {outcome.alerted}")
    for key, value in outcome.detail.items():
        print(f"  {key}: {value}")
    return 0 if outcome.ok else 1


def _run_schedule_run(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"schedule run error: {exc}", file=sys.stderr)
        return 2

    ctx = build_job_context(cfg)
    scheduler = build_scheduler(ctx)
    jobs = scheduler.get_jobs()
    if not jobs:
        print("schedule run: no cron jobs configured; nothing to run", file=sys.stderr)
        return 2
    print(f"schedule run: starting {len(jobs)} job(s); press Ctrl+C to stop")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
    return 0


def _split_symbols(raw: str) -> list[str]:
    return [symbol for chunk in raw.split(",") for symbol in [chunk.strip()] if symbol]


def _parse_weights(raw: str | None, symbols: list[str]) -> dict[str, float]:
    if raw is None or not raw.strip():
        weight = 1.0 / len(symbols)
        return {symbol: weight for symbol in symbols}
    values = [float(chunk.strip()) for chunk in raw.split(",") if chunk.strip()]
    if len(values) != len(symbols):
        raise ValueError("--weights must have one value per symbol")
    if any(value < 0 for value in values):
        raise ValueError("--weights must be non-negative")
    if sum(values) > 1.0 + 1e-9:
        raise ValueError("--weights must sum to at most 1.0")
    return dict(zip(symbols, values, strict=True))


def _static_target_provider(weights: dict[str, float]) -> TargetProvider:
    from yquant.strategies.base import Layer, TargetPortfolio

    placed = {"done": False}

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if placed["done"]:
            return None
        if not all(symbol in closes for symbol in weights):
            return None
        placed["done"] = True
        layers: dict[str, Layer] = {symbol: "core" for symbol in weights}
        return TargetPortfolio(
            as_of=day,
            weights=dict(weights),
            layers=layers,
            cash_weight=max(0.0, 1.0 - sum(weights.values())),
        )

    return provider


def _run_backtest(args: argparse.Namespace) -> int:
    import json
    from typing import cast

    from yquant.backtest import Instrument, UsCostModel, build_report

    try:
        cfg = load_config(args.config)
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        if end < start:
            raise ValueError("--end must be on or after --start")
        symbols = normalize_symbols(_split_symbols(args.symbols))
        if not symbols:
            raise ValueError("--symbols must include at least one ticker")
        weights = _parse_weights(args.weights, symbols)
        if args.initial_cash <= 0:
            raise ValueError("--initial-cash must be positive")
    except (ConfigError, ValueError) as exc:
        print(f"backtest error: {exc}", file=sys.stderr)
        return 2

    single_stocks = set(normalize_symbols(_split_symbols(args.single_stocks or "")))
    instruments: dict[str, Instrument] = {
        symbol: ("single_stock" if symbol in single_stocks else "etf") for symbol in symbols
    }
    benchmark = normalize_symbols([args.benchmark])[0]

    repo = LocalDataRepo(cfg.runtime.parquet_dir)
    load_symbols = sorted({*symbols, benchmark})
    bars = repo.get_bars(load_symbols, start, end, "adjusted")
    if bars.empty:
        print("backtest error: no bars found for the requested range", file=sys.stderr)
        return 1

    cost_model = UsCostModel.from_rates(
        commission_per_trade=cfg.cost.commission_per_trade_usd,
        sec_fee_rate=cfg.cost.sec_fee_rate,
        finra_taf_per_share=cfg.cost.finra_taf_per_share,
        finra_taf_cap=cfg.cost.finra_taf_cap_usd,
        slippage_rate_etf=cfg.cost.slippage_rate_etf,
        slippage_rate_single=cfg.cost.slippage_rate_single,
    )
    report = build_report(
        bars=bars,
        target_provider=_static_target_provider(weights),
        initial_cash=args.initial_cash,
        cost_model=cost_model,
        instruments=instruments,
        benchmark_symbol=benchmark,
    )

    strategy = cast("dict[str, object]", report["strategy"])
    metrics = cast("dict[str, float]", strategy["metrics"])
    print("backtest: deterministic engine")
    print(f"symbols: {', '.join(symbols)}")
    print(f"range: {start.isoformat()}..{end.isoformat()}")
    print(f"digest: {strategy['digest']}")
    print(f"total_return: {metrics['total_return']:.4f}")
    print(f"annualized_return: {metrics['annualized_return']:.4f}")
    print(f"max_drawdown: {metrics['max_drawdown']:.4f}")
    print(f"gfv_count: {metrics['gfv_count']}")
    benchmark_block = cast("dict[str, object] | None", report["benchmark"])
    if benchmark_block is not None:
        bench_metrics = cast("dict[str, float]", benchmark_block["metrics"])
        print(f"benchmark {benchmark}: total_return={bench_metrics['total_return']:.4f}")
    for tier in cast("list[dict[str, object]]", report["cost_sensitivity"]):
        tier_metrics = cast("dict[str, float]", tier["metrics"])
        print(f"cost {tier['tier']}: final_equity={tier_metrics['final_equity']:.2f}")
    for warning in cast("list[str]", report["warnings"]):
        print(f"warning: {warning}")
    rejections = cast("list[object]", report["rejections"])
    if rejections:
        print(f"rejections: {len(rejections)}")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report_artifact: {args.output}")
    return 0


def _run_qa(args: argparse.Namespace) -> int:
    if args.qa_command == "golden":
        return _run_qa_golden(args)
    if args.qa_command == "panel":
        return _run_qa_panel(args)
    if args.qa_command == "drills":
        return _run_qa_drills(args)
    return 0


def _run_qa_golden(args: argparse.Namespace) -> int:
    from yquant.qa import GOLDEN_WINDOWS, golden_content_hash, golden_manifest

    keys = [w.key for w in GOLDEN_WINDOWS] if args.window == "all" else [args.window]
    try:
        print("qa_golden: frozen regression / drill windows (06 §4)")
        for key in keys:
            manifest = golden_manifest(key)
            print(f"- {key}")
            print(f"  content_hash: {golden_content_hash(key)}")
            print(f"  manifest_id: {manifest.manifest_id}")
            print(f"  rows: {manifest.row_count}")
    except KeyError as exc:
        print(f"qa golden error: {exc}", file=sys.stderr)
        return 2
    return 0


def _golden_panel_provider() -> TargetProvider:
    """A full-layer target (core + satellite + overlay) over the golden universe."""

    from yquant.strategies.base import Layer, TargetPortfolio

    placed = {"done": False}
    weights = {"SPY": 0.5, "TLT": 0.2, "GLD": 0.1, "QQQ": 0.08}
    layers: dict[str, Layer] = {
        "SPY": "core",
        "TLT": "core",
        "GLD": "satellite",
        "QQQ": "overlay",
    }

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if placed["done"] or not all(symbol in closes for symbol in weights):
            return None
        placed["done"] = True
        return TargetPortfolio(
            as_of=day, weights=dict(weights), layers=dict(layers), cash_weight=0.12
        )

    return provider


def _golden_regime_readings() -> list[RegimeReading]:
    """A short regime series (one fully-stale period) to exercise P10 availability."""

    from yquant.risk.state_machine import RegimeInputs, replay

    full = RegimeInputs(
        spy_close=100.0,
        spy_ma_10m=90.0,
        pct_sectors_above_200d=0.7,
        hy_oas_percentile=0.3,
        hy_oas_change_3m_bp=-60.0,
        hyg_lqd_z=0.5,
        vix_level=13.0,
        vix_term_inversion_days=0,
        rsp_spy_trend_slope=0.1,
        pct_above_200d=0.7,
        nfci=-0.3,
        nfci_change=-0.1,
        curve_10y_3m=0.5,
        usd_change_3m=0.0,
    )
    series = [
        (date(2024, 1, 5), full),
        (date(2024, 1, 12), RegimeInputs()),  # carried forward -> stale but available
        (date(2024, 1, 19), full),
    ]
    return [reading for _, reading in replay(series)]


def _run_qa_panel(args: argparse.Namespace) -> int:
    import json

    import pandas as pd

    from yquant.backtest.engine import run_backtest
    from yquant.datasrc.bars import repo_view
    from yquant.datasrc.reconcile import reconcile_daily_bars
    from yquant.qa import (
        build_golden_bars,
        build_panel,
        check_p1_accounting_conservation,
        check_p2_nav_double_calc,
        check_p3_source_consistency,
        check_p4_adjusted_price_continuity,
        check_p6_digest_reproducible,
        check_p10_state_machine_availability,
        check_p11_layer_budget,
    )
    from yquant.qa.metrics import last_close_by_symbol

    if args.initial_cash <= 0:
        print("qa panel error: --initial-cash must be positive", file=sys.stderr)
        return 2
    try:
        storage = build_golden_bars(args.window)
    except KeyError as exc:
        print(f"qa panel error: {exc}", file=sys.stderr)
        return 2

    bars = repo_view(storage)
    result = run_backtest(
        bars=bars, target_provider=_golden_panel_provider(), initial_cash=args.initial_cash
    )

    right = storage.copy()
    right["source"] = "stooq"
    reconciliation = reconcile_daily_bars(
        storage, right, left_source="golden", right_source="stooq"
    )

    spy = bars.loc[bars["symbol"] == "SPY", ["date", "close"]].sort_values("date")
    spy_dates = pd.to_datetime(spy["date"]).dt.date
    adjusted = [(d, float(c)) for d, c in zip(spy_dates, spy["close"], strict=True)]

    results = [
        check_p1_accounting_conservation(result),
        check_p2_nav_double_calc(result, last_close_by_symbol(bars)),
        check_p3_source_consistency(reconciliation),
        check_p4_adjusted_price_continuity(adjusted, event_dates=[]),
        check_p6_digest_reproducible(
            bars=bars,
            provider_factory=_golden_panel_provider,
            initial_cash=args.initial_cash,
        ),
        check_p10_state_machine_availability(_golden_regime_readings()),
        check_p11_layer_budget({"core": 0.7, "satellite": 0.1, "overlay": 0.08}),
    ]
    panel = build_panel(results)
    print(f"qa_panel: {args.window}")
    print(panel.render_text())

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(panel.as_dict(), indent=2), encoding="utf-8")
        print(f"panel_artifact: {args.output}")
    return 0 if panel.passed else 1


def _run_qa_drills(args: argparse.Namespace) -> int:
    import json

    from yquant.qa import build_drill_ledger

    records = build_drill_ledger()
    print("qa_drills: historical-event + fire drill台账 (06 §5, contaminated)")
    for record in records:
        if record.kind == "historical_event":
            detail = record.detail
            print(
                f"- {record.key}: {detail['start_state']} -> {detail['end_state']} "
                f"(peak_severity={detail['peak_severity']}, periods={detail['periods']})"
            )
        else:
            alerts = record.detail["alerts"]
            assert isinstance(alerts, list)
            print(f"- {record.key}: {len(alerts)} S1 alert(s) routed to banner+feishu")
    print(f"records: {len(records)} (all contaminated; process check, not a performance claim)")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"records": [r.as_dict() for r in records]}
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"drill_ledger_artifact: {args.output}")
    return 0


def _run_ledger(args: argparse.Namespace) -> int:
    if args.ledger_command == "replay":
        return _run_ledger_replay(args)
    if args.ledger_command == "collect":
        return _run_ledger_collect(args)
    if args.ledger_command == "chain":
        return _run_ledger_chain(args)
    return 0


def _run_ledger_replay(args: argparse.Namespace) -> int:
    from yquant.ledger import LedgerStore
    from yquant.ledger.replay import replay_run

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"ledger replay error: {exc}", file=sys.stderr)
        return 2

    store = LedgerStore(cfg.runtime.sqlite_path)
    store.bootstrap()
    result = replay_run(store, args.run_id)
    print("ledger replay")
    print(f"run_id: {result.run_id}")
    print(f"event_count: {result.event_count}")
    print(f"recorded_digest: {result.recorded_digest}")
    print(f"recomputed_digest: {result.recomputed_digest}")
    print(f"consistent: {result.consistent}")
    for warning in result.provenance_warnings:
        print(f"warning: {warning}")
    if result.first_divergence is not None:
        print(f"first_divergence: {result.first_divergence}")
    if args.strict and not result.strict_ok:
        print("strict replay failed", file=sys.stderr)
        return 1
    return 0


def _run_ledger_collect(args: argparse.Namespace) -> int:
    import json

    from yquant.ledger import LedgerStore
    from yquant.ledger.incident import collect_incident

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"ledger collect error: {exc}", file=sys.stderr)
        return 2

    store = LedgerStore(cfg.runtime.sqlite_path)
    store.bootstrap()
    evidence = collect_incident(store, args.run_id)
    print("ledger incident collect")
    print(f"run_id: {evidence.run_id}")
    print(f"event_count: {evidence.event_count}")
    print(f"kinds: {', '.join(evidence.kinds) if evidence.kinds else '(none)'}")
    print(f"replay_strict_ok: {evidence.replay.strict_ok}")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence.as_dict(), indent=2), encoding="utf-8")
        print(f"evidence_bundle: {args.output}")
    return 0


def _run_ledger_chain(args: argparse.Namespace) -> int:
    from yquant.ledger import LedgerStore

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"ledger chain error: {exc}", file=sys.stderr)
        return 2

    store = LedgerStore(cfg.runtime.sqlite_path)
    store.bootstrap()
    chain = store.causal_chain(args.event_id)
    print("ledger causal chain")
    print(f"leaf_event_id: {args.event_id}")
    print(f"depth: {len(chain)}")
    for record in chain:
        event = record.event
        print(f"- {event.event_id} {event.kind} (run={event.run_id})")
    return 0


def _parse_deadline_utc(raw: str | None) -> datetime | None:
    if raw is None or not raw.strip():
        return None
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _freshness_deadline(args: argparse.Namespace, expected_date: date) -> datetime | None:
    if args.deadline_utc and args.use_calendar_deadline:
        raise ValueError("--deadline-utc and --use-calendar-deadline are mutually exclusive")
    if args.use_calendar_deadline:
        return expected_daily_bar_deadline_utc(
            expected_date,
            minutes_after_close=args.minutes_after_close,
            calendar_name=args.calendar,
        )
    return _parse_deadline_utc(args.deadline_utc)


def _quality_output_dir(data_dir: Path, override: Path | None) -> Path:
    return override if override is not None else data_dir / "quality"


def _daily_bar_source(source_name: str) -> DailyBarSource:
    try:
        return build_daily_bar_source(source_name)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _daily_bar_sources(source_names: list[str]) -> list[DailyBarSource]:
    try:
        return build_daily_bar_sources(source_names)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _run_probe(args: argparse.Namespace) -> int:
    if args.probe_name == "yfinance":
        run = run_yfinance_probe(
            us_symbol=args.us_symbol,
            index_symbol=args.index_symbol,
        )
        return _write_and_print_probe(run, args.output_dir)
    if args.probe_name == "stooq":
        run = run_stooq_probe(us_symbol=args.us_symbol, index_symbol=args.index_symbol)
        return _write_and_print_probe(run, args.output_dir)
    if args.probe_name == "edgar":
        run = run_edgar_probe(symbol=args.symbol, user_agent=os.getenv(args.user_agent_env))
        return _write_and_print_probe(run, args.output_dir)
    if args.probe_name == "calendar":
        run = run_calendar_probe(start=args.start, end=args.end)
        return _write_and_print_probe(run, args.output_dir)
    if args.probe_name == "all":
        return _run_probe_all(args)
    return 0


def _run_probe_all(args: argparse.Namespace) -> int:
    commands = [
        ("yfinance", ["probe", "yfinance", "--us-symbol", args.us_symbol,
                      "--index-symbol", args.index_symbol]),
        ("stooq", ["probe", "stooq", "--us-symbol", args.us_symbol]),
        ("edgar", ["probe", "edgar", "--symbol", args.us_symbol]),
        ("calendar", ["probe", "calendar"]),
    ]
    exit_code = 0
    for probe_name, command_args in commands:
        exit_code = max(
            exit_code,
            _run_probe_subprocess(
                probe_name=probe_name,
                command_args=command_args,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout_seconds,
            ),
        )
    return exit_code


def _write_and_print_probe(run: ProbeRun, output_dir: Path) -> int:
    output_path = write_probe_run(run, output_dir)
    print(f"probe: {run.probe_name}")
    print(f"status: {run.status}")
    print(f"output: {output_path}")
    for check in run.checks:
        print(f"- {check.name}: {check.status}")
        if check.error:
            print(f"  error: {check.error}")
    return 0 if run.status != "failed" else 1


def _run_probe_subprocess(
    *,
    probe_name: str,
    command_args: list[str],
    output_dir: Path,
    timeout_seconds: int,
) -> int:
    command = [sys.executable, "-m", "yquant", *command_args, "--output-dir", str(output_dir)]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        run = make_probe_run(
            probe_name=probe_name,
            started_at=utc_now_iso(),
            checks=[
                CheckResult(
                    name="probe_subprocess",
                    status="failed",
                    duration_seconds=float(timeout_seconds),
                    error=f"timed out after {timeout_seconds}s: {' '.join(exc.cmd)}",
                )
            ],
        )
        return _write_and_print_probe(run, output_dir)

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
