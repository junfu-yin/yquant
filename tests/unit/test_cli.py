from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from yquant.cli import _daily_bar_sources, _parse_deadline_utc, _split_symbols, build_parser


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
