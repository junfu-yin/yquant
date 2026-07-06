"""Command line interface for local development and operations."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from yquant.config import ConfigError, load_config
from yquant.probes.calendar import run_calendar_probe
from yquant.probes.edgar import run_edgar_probe
from yquant.probes.models import CheckResult, ProbeRun, make_probe_run, utc_now_iso, write_probe_run
from yquant.probes.stooq import run_stooq_probe
from yquant.probes.yfinance_probe import run_yfinance_probe
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
    if args.command == "probe":
        return _run_probe(args)

    parser.print_help()
    return 0


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
