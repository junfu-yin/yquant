from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from yquant.cli import (
    _daily_bar_sources,
    _parse_deadline_utc,
    _run_data_reconcile,
    _split_symbols,
    build_parser,
)
from yquant.datasrc.artifacts import read_report_artifact
from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.repo import LocalDataRepo


def test_data_update_parser_accepts_symbols_and_dates() -> None:
    args = build_parser().parse_args(
        [
            "data",
            "update",
            "--config",
            "config.example.toml",
            "--symbols",
            "aapl, msft",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-31",
        ]
    )

    assert args.command == "data"
    assert args.data_command == "update"
    assert args.config == Path("config.example.toml")
    assert args.symbols == "aapl, msft"
    assert args.start == "2024-01-01"
    assert args.end == "2024-01-31"


def test_data_freshness_parser_accepts_expected_date_and_deadline() -> None:
    args = build_parser().parse_args(
        [
            "data",
            "freshness",
            "--symbols",
            "aapl",
            "--expected-date",
            "2024-01-31",
            "--deadline-utc",
            "2024-02-01T00:45:00Z",
        ]
    )

    assert args.command == "data"
    assert args.data_command == "freshness"
    assert args.symbols == "aapl"
    assert args.expected_date == "2024-01-31"
    assert args.deadline_utc == "2024-02-01T00:45:00Z"


def test_data_freshness_parser_accepts_calendar_deadline() -> None:
    args = build_parser().parse_args(
        [
            "data",
            "freshness",
            "--symbols",
            "aapl",
            "--expected-date",
            "2024-01-31",
            "--use-calendar-deadline",
            "--minutes-after-close",
            "45",
        ]
    )

    assert args.use_calendar_deadline is True
    assert args.minutes_after_close == 45
    assert args.calendar == "NYSE"


def test_data_reconcile_parser_accepts_sources_and_thresholds() -> None:
    args = build_parser().parse_args(
        [
            "data",
            "reconcile",
            "--symbols",
            "aapl,msft",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-31",
            "--left-source",
            "yfinance",
            "--right-source",
            "stooq",
            "--tolerance-bps",
            "12.5",
            "--minimum-consistency-rate",
            "0.99",
        ]
    )

    assert args.command == "data"
    assert args.data_command == "reconcile"
    assert args.left_source == "yfinance"
    assert args.right_source == "stooq"
    assert args.tolerance_bps == 12.5
    assert args.minimum_consistency_rate == 0.99


def test_data_reconcile_cli_writes_quality_artifact(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path / "parquet")
    repo.write_daily_bars(
        pd.concat(
            [
                _bars("AAPL", "yfinance"),
                _bars("AAPL", "stooq"),
            ],
            ignore_index=True,
        )
    )
    config = _write_config(tmp_path)
    quality_dir = tmp_path / "quality"
    args = build_parser().parse_args(
        [
            "data",
            "reconcile",
            "--config",
            str(config),
            "--symbols",
            "AAPL",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-31",
            "--quality-dir",
            str(quality_dir),
        ]
    )

    exit_code = _run_data_reconcile(args)
    artifacts = list(quality_dir.glob("*_daily_bars_reconciliation.json"))

    assert exit_code == 0
    assert len(artifacts) == 1
    payload = read_report_artifact(artifacts[0])
    assert payload["report"]["passed"] is True
    assert payload["report"]["compared_rows"] == 2


def test_split_symbols_trims_empty_chunks() -> None:
    assert _split_symbols(" aapl, ,msft ") == ["aapl", "msft"]


def test_parse_deadline_utc_handles_z_suffix() -> None:
    assert _parse_deadline_utc("2024-02-01T00:45:00Z") == datetime(
        2024,
        2,
        1,
        0,
        45,
        tzinfo=UTC,
    )


def test_daily_bar_sources_deduplicates_configured_sources() -> None:
    sources = _daily_bar_sources(["yfinance", "stooq", "YFINANCE"])

    assert [source.name for source in sources] == ["yfinance", "stooq"]


def _bars(symbol: str, source: str) -> pd.DataFrame:
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"])),
        raw_open=pd.Series([99.0, 101.0]),
        raw_high=pd.Series([101.0, 103.0]),
        raw_low=pd.Series([98.0, 100.0]),
        raw_close=pd.Series([100.0, 102.0]),
        volume=pd.Series([1_000, 1_100]),
        source=source,
        asof=datetime(2024, 1, 4, tzinfo=UTC),
    )


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[runtime]
timezone = "America/New_York"
data_dir = "{(tmp_path / "data").as_posix()}"
sqlite_path = "{(tmp_path / "data" / "yquant.db").as_posix()}"
parquet_dir = "{(tmp_path / "parquet").as_posix()}"
log_dir = "{(tmp_path / "data" / "logs").as_posix()}"

[data]
markets = ["us"]
primary_source = "yfinance"
backup_sources = ["stooq"]
history_start = "2010-01-01"

[llm]
provider = "deepseek"
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
api_key_env = "YQUANT_LLM_API_KEY"
timeout_seconds = 45
max_input_chars = 8000

[risk]
core_budget = 0.75
satellite_budget = 0.15
overlay_budget = 0.10
single_position_limit = 0.15
overlay_single_position_limit = 0.05
leveraged_etf_total_limit = 0.05
leveraged_etf_single_limit = 0.03
industry_position_limit = 0.35
drawdown_warning = 0.10
drawdown_strong_warning = 0.15
cooldown_loss_count = 3
cooldown_trading_days = 3

[notification.feishu]
webhook_env = "YQUANT_FEISHU_WEBHOOK"
""",
        encoding="utf-8",
    )
    return config_path
