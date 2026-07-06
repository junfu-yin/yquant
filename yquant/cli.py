"""Command line interface for local development and operations."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

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
