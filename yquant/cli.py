"""Command line interface for local development and operations."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from yquant.config import ConfigError, load_config
from yquant.probes.akshare import run_akshare_probe
from yquant.probes.baostock import run_baostock_probe
from yquant.probes.models import ProbeRun, write_probe_run
from yquant.probes.tushare import run_tushare_probe
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

    akshare = probe_subparsers.add_parser("akshare", help="probe AkShare interfaces")
    akshare.add_argument("--symbol", default="600000", help="A-share symbol for sample bar fetch")
    akshare.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/probes"),
        help="directory for JSON probe evidence",
    )

    tushare = probe_subparsers.add_parser("tushare", help="probe Tushare Pro interfaces")
    tushare.add_argument("--ts-code", default="600000.SH", help="Tushare ts_code for sample calls")
    tushare.add_argument(
        "--token-env",
        default="YQUANT_TUSHARE_TOKEN",
        help="Tushare token env var",
    )
    tushare.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/probes"),
        help="directory for JSON probe evidence",
    )

    baostock = probe_subparsers.add_parser("baostock", help="probe BaoStock interfaces")
    baostock.add_argument("--code", default="sh.600000", help="BaoStock code for sample calls")
    baostock.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/probes"),
        help="directory for JSON probe evidence",
    )

    all_sources = probe_subparsers.add_parser("all", help="probe all configured data sources")
    all_sources.add_argument("--akshare-symbol", default="600000")
    all_sources.add_argument("--tushare-ts-code", default="600000.SH")
    all_sources.add_argument("--tushare-token-env", default="YQUANT_TUSHARE_TOKEN")
    all_sources.add_argument("--baostock-code", default="sh.600000")
    all_sources.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/probes"),
        help="directory for JSON probe evidence",
    )

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
    if args.command == "probe" and args.probe_name == "akshare":
        run = run_akshare_probe(symbol=args.symbol)
        return _write_and_print_probe(run, args.output_dir)
    if args.command == "probe" and args.probe_name == "tushare":
        run = run_tushare_probe(ts_code=args.ts_code, token_env=args.token_env)
        return _write_and_print_probe(run, args.output_dir)
    if args.command == "probe" and args.probe_name == "baostock":
        run = run_baostock_probe(code=args.code)
        return _write_and_print_probe(run, args.output_dir)
    if args.command == "probe" and args.probe_name == "all":
        runs = [
            run_akshare_probe(symbol=args.akshare_symbol),
            run_tushare_probe(ts_code=args.tushare_ts_code, token_env=args.tushare_token_env),
            run_baostock_probe(code=args.baostock_code),
        ]
        exit_code = 0
        for run in runs:
            exit_code = max(exit_code, _write_and_print_probe(run, args.output_dir))
        return exit_code

    parser.print_help()
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
