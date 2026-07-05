"""Command line interface for local development and operations."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from yquant.config import ConfigError, load_config
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

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

