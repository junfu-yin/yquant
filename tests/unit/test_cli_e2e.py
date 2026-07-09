"""End-to-end CLI tests driving main(argv) for each subcommand.

Offline subcommands run for real against a tmp config/repo; network-facing ones
(update, update-macro) run with the source factory monkeypatched to fakes, so
the full parse -> dispatch -> handler -> artifact/ledger path is exercised
without egress.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

import yquant.cli as cli
from yquant.cli import main
from yquant.datasrc.bars import make_daily_bars_frame
from yquant.datasrc.repo import LocalDataRepo


def _bars(symbol: str, source: str) -> pd.DataFrame:
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(pd.to_datetime(["2024-01-30", "2024-01-31"])),
        raw_open=pd.Series([99.0, 101.0]),
        raw_high=pd.Series([101.0, 103.0]),
        raw_low=pd.Series([98.0, 100.0]),
        raw_close=pd.Series([100.0, 102.0]),
        volume=pd.Series([1_000, 1_100]),
        source=source,
        asof=datetime(2024, 1, 31, 21, 0, tzinfo=UTC),
    )


class _FakeSource:
    def __init__(self, name: str, frames: dict[str, pd.DataFrame]) -> None:
        self.name = name
        self.frames = frames

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self.frames.get(symbol, pd.DataFrame())


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

[schedule]
symbols = ["AAPL"]
freshness_cron = "45 17 * * 1-5"
""",
        encoding="utf-8",
    )
    return config_path


def test_doctor_runs(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    assert main(["doctor", "--config", str(cfg)]) == 0


def test_no_command_prints_help() -> None:
    assert main([]) == 0


def test_update_then_freshness_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(tmp_path)
    fake = _FakeSource("yfinance", {"AAPL": _bars("AAPL", "yfinance")})
    monkeypatch.setattr(cli, "build_daily_bar_sources", lambda names: [fake])

    assert main(
        ["data", "update", "--config", str(cfg), "--symbols", "AAPL",
         "--start", "2024-01-30", "--end", "2024-01-31"]
    ) == 0
    # Freshness now passes because the bar is present for the expected date.
    assert main(
        ["data", "freshness", "--config", str(cfg), "--symbols", "AAPL",
         "--expected-date", "2024-01-31"]
    ) == 0


def test_reconcile_cli_on_seeded_repo(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    repo = LocalDataRepo(tmp_path / "parquet")
    repo.write_daily_bars(pd.concat([_bars("AAPL", "yfinance"), _bars("AAPL", "stooq")]))

    assert main(
        ["data", "reconcile", "--config", str(cfg), "--symbols", "AAPL",
         "--start", "2024-01-01", "--end", "2024-01-31"]
    ) == 0


def test_load_securities_then_universe(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _write_config(tmp_path)
    csv = tmp_path / "securities.csv"
    csv.write_text(
        "symbol,market,listing_date,delisting_date\n"
        "AAPL,us,1980-12-12,\n"
        "DEADCO,us,2015-01-05,2020-06-30\n",
        encoding="utf-8",
    )

    assert main(["data", "load-securities", "--config", str(cfg), "--csv", str(csv)]) == 0
    assert main(
        ["data", "universe", "--config", str(cfg), "--on-date", "2019-06-30", "--market", "us"]
    ) == 0
    out = capsys.readouterr().out
    assert "DEADCO" in out  # tradable in 2019
    assert "security_master" in out


def test_update_macro_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(tmp_path)

    class _FakeMacro:
        name = "yfinance"

        def fetch_series(self, series_id: str, start: date, end: date) -> pd.DataFrame:
            dates = pd.date_range("2024-01-02", periods=2, freq="D")
            return pd.DataFrame(
                {"series_id": series_id, "date": dates, "value": [10.0, 11.0], "source": "test"}
            )

    monkeypatch.setattr("yquant.datasrc.macro.YFinanceMacroSource", _FakeMacro)

    assert main(
        ["data", "update-macro", "--config", str(cfg), "--series", "^VIX",
         "--start", "2024-01-02", "--end", "2024-01-03"]
    ) == 0
    stored = LocalDataRepo(tmp_path / "parquet").get_macro_series(
        ["^VIX"], date(2024, 1, 1), date(2024, 1, 31)
    )
    assert list(stored["value"]) == [10.0, 11.0]


def test_asof_cli(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    LocalDataRepo(tmp_path / "parquet").write_daily_bars(_bars("AAPL", "yfinance"))

    assert main(
        ["data", "asof", "--config", str(cfg), "--symbols", "AAPL",
         "--start", "2024-01-01", "--end", "2024-01-31",
         "--as-of-utc", "2024-02-01T00:00:00Z"]
    ) == 0


def test_schedule_list_and_run_once(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    LocalDataRepo(tmp_path / "parquet").write_daily_bars(_bars("AAPL", "yfinance"))

    assert main(["schedule", "list", "--config", str(cfg)]) == 0
    # Freshness run-once succeeds because the bar is present.
    assert main(
        ["schedule", "run-once", "--config", str(cfg), "--job", "freshness",
         "--on-date", "2024-01-31"]
    ) == 0


def test_invalid_dates_return_error_code(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    assert main(
        ["data", "asof", "--config", str(cfg), "--symbols", "AAPL",
         "--start", "not-a-date", "--end", "2024-01-31", "--as-of-utc", "2024-02-01T00:00:00Z"]
    ) == 2


def _rising_bars(symbol: str, closes: list[float], source: str = "yfinance") -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=len(closes), freq="B")
    series = pd.Series(closes)
    return make_daily_bars_frame(
        symbol=symbol,
        market="us",
        dates=pd.Series(pd.to_datetime(dates)),
        raw_open=series,
        raw_high=series + 1.0,
        raw_low=series - 1.0,
        raw_close=series,
        volume=pd.Series([1_000] * len(closes)),
        source=source,
        asof=datetime(2024, 3, 1, 21, 0, tzinfo=UTC),
    )


def test_backtest_cli_runs_and_writes_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _write_config(tmp_path)
    repo = LocalDataRepo(tmp_path / "parquet")
    repo.write_daily_bars(_rising_bars("SPY", [100.0, 105.0, 110.0, 115.0, 120.0]))
    out_path = tmp_path / "report.json"

    code = main(
        ["backtest", "--config", str(cfg), "--symbols", "SPY",
         "--start", "2024-01-01", "--end", "2024-03-01",
         "--initial-cash", "100000", "--output", str(out_path)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "backtest: deterministic engine" in out
    assert "digest:" in out
    assert "cost 0x:" in out and "cost 2x:" in out
    assert out_path.exists()

    import json

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["benchmark"]["symbol"] == "SPY"
    tiers = [row["tier"] for row in report["cost_sensitivity"]]
    assert tiers == ["0x", "1x", "2x"]


def test_backtest_cli_errors_on_empty_repo(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    LocalDataRepo(tmp_path / "parquet")  # empty repo, no bars written.

    code = main(
        ["backtest", "--config", str(cfg), "--symbols", "SPY",
         "--start", "2024-01-01", "--end", "2024-03-01"]
    )
    assert code == 1


def test_backtest_cli_rejects_mismatched_weights(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    repo = LocalDataRepo(tmp_path / "parquet")
    repo.write_daily_bars(_rising_bars("SPY", [100.0, 105.0]))

    code = main(
        ["backtest", "--config", str(cfg), "--symbols", "SPY,QQQ",
         "--weights", "1.0", "--start", "2024-01-01", "--end", "2024-03-01"]
    )
    assert code == 2


def test_backtest_parser_defaults() -> None:
    from yquant.cli import build_parser

    args = build_parser().parse_args(
        ["backtest", "--symbols", "SPY", "--start", "2024-01-01", "--end", "2024-03-01"]
    )
    assert args.command == "backtest"
    assert args.initial_cash == 100_000.0
    assert args.benchmark == "SPY"


def _seed_macro(tmp_path: Path) -> None:
    repo = LocalDataRepo(tmp_path / "parquet")
    repo.write_macro_series(
        pd.DataFrame(
            {
                "series_id": "^VIX",
                "date": [date(2024, 1, 2), date(2024, 1, 3)],
                "value": [13.0, 14.0],
                "source": "yfinance",
                "asof": datetime(2024, 1, 4, tzinfo=UTC),
            }
        )
    )


def test_asof_cli_macro_series(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = _write_config(tmp_path)
    _seed_macro(tmp_path)

    assert main(
        ["data", "asof", "--config", str(cfg), "--series", "^VIX",
         "--start", "2024-01-01", "--end", "2024-01-31",
         "--as-of-utc", "2024-02-01T00:00:00Z"]
    ) == 0
    out = capsys.readouterr().out
    assert "macro_series_rows: 2" in out


def test_asof_cli_requires_symbols_or_series(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    assert main(
        ["data", "asof", "--config", str(cfg),
         "--start", "2024-01-01", "--end", "2024-01-31",
         "--as-of-utc", "2024-02-01T00:00:00Z"]
    ) == 2


def _seed_ledger_run(tmp_path: Path) -> str:
    from yquant.ledger import Event, LedgerStore, Provenance, new_event_id

    store = LedgerStore(tmp_path / "data" / "yquant.db")
    store.bootstrap()
    prov = Provenance(git_sha="g", config_hash="c", data_manifest_id="m")
    root = Event(
        event_id=new_event_id(datetime(2024, 1, 3, 12, 0, tzinfo=UTC), entropy=b"\x00" * 10),
        ts=datetime(2024, 1, 3, 12, 0, tzinfo=UTC),
        kind="data_ingested",
        payload={"n": 1},
        run_id="run-x",
        dedup_key="data_ingested:x",
        provenance=prov,
    )
    leaf = Event(
        event_id=new_event_id(datetime(2024, 1, 3, 12, 1, tzinfo=UTC), entropy=b"\x01" * 10),
        ts=datetime(2024, 1, 3, 12, 1, tzinfo=UTC),
        kind="signal",
        payload={"n": 2},
        run_id="run-x",
        dedup_key="signal:x",
        provenance=prov,
        causation_id=root.event_id,
    )
    store.append_event(root)
    store.append_event(leaf)
    store.record_run_digest("run-x")
    return leaf.event_id


def test_ledger_replay_collect_chain_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _write_config(tmp_path)
    leaf_id = _seed_ledger_run(tmp_path)

    assert main(["ledger", "replay", "--config", str(cfg), "--run-id", "run-x", "--strict"]) == 0
    assert "consistent: True" in capsys.readouterr().out

    bundle = tmp_path / "incident.json"
    assert main(
        ["ledger", "collect", "--config", str(cfg), "--run-id", "run-x",
         "--output", str(bundle)]
    ) == 0
    assert bundle.exists()

    assert main(["ledger", "chain", "--config", str(cfg), "--event-id", leaf_id]) == 0
    assert "depth: 2" in capsys.readouterr().out


def test_qa_golden_cli_prints_hashes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["qa", "golden", "--window", "2020_covid"]) == 0
    out = capsys.readouterr().out
    assert "2020_covid" in out
    assert "content_hash:" in out
    assert "manifest_id:" in out


def test_qa_golden_cli_all_windows(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["qa", "golden"]) == 0
    out = capsys.readouterr().out
    for key in ("2020_covid", "2022_hikes", "2023_svb", "2024_carry"):
        assert key in out


def test_qa_golden_cli_rejects_unknown_window() -> None:
    assert main(["qa", "golden", "--window", "not_a_window"]) == 2


def test_qa_panel_cli_is_green_and_writes_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    out_path = tmp_path / "panel.json"
    code = main(
        ["qa", "panel", "--window", "2023_svb", "--initial-cash", "50000",
         "--output", str(out_path)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "qa_panel: 2023_svb" in out
    assert "verdict: GREEN" in out
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    metric_ids = [m["metric"] for m in payload["metrics"]]
    assert metric_ids == ["P1", "P2", "P3", "P4", "P6", "P10", "P11"]


def test_qa_panel_cli_rejects_bad_cash() -> None:
    assert main(["qa", "panel", "--window", "2020_covid", "--initial-cash", "0"]) == 2


def test_qa_drills_cli_writes_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    out_path = tmp_path / "drills.json"
    assert main(["qa", "drills", "--output", str(out_path)]) == 0
    out = capsys.readouterr().out
    assert "qa_drills:" in out
    assert "fire_drill:" in out
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    kinds = [r["kind"] for r in payload["records"]]
    assert kinds.count("historical_event") == 4
    assert kinds.count("fire") == 1
    assert all(r["contaminated"] for r in payload["records"])


def test_paper_cli_parity_passes_and_writes_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    out_path = tmp_path / "shadow.json"
    code = main(
        ["paper", "--window", "2020_covid", "--initial-cash", "50000",
         "--min-sessions", "20", "--output", str(out_path)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "shadow_verdict: PASS" in out
    assert "digest_match: True" in out
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["reconciliation_breaches"] == 0
    assert payload["parity"]["max_daily_bps"] == 0.0


def test_paper_cli_rejects_unknown_window() -> None:
    assert main(["paper", "--window", "not_a_window"]) == 2


def test_paper_cli_rejects_bad_cash() -> None:
    assert main(["paper", "--initial-cash", "0"]) == 2


def test_paper_cli_fails_when_min_sessions_not_met(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # SVB window has fewer sessions than an impossible 10,000-session gate.
    assert main(["paper", "--window", "2023_svb", "--min-sessions", "100000"]) == 1
    out = capsys.readouterr().out
    assert "shadow_verdict: FAIL" in out
