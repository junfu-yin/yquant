from __future__ import annotations

from pathlib import Path

from yquant.cli import _daily_bar_sources, _split_symbols, build_parser


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


def test_split_symbols_trims_empty_chunks() -> None:
    assert _split_symbols(" aapl, ,msft ") == ["aapl", "msft"]


def test_daily_bar_sources_deduplicates_configured_sources() -> None:
    sources = _daily_bar_sources(["yfinance", "stooq", "YFINANCE"])

    assert [source.name for source in sources] == ["yfinance", "stooq"]
