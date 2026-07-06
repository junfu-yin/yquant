from __future__ import annotations

import importlib
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from yquant.probes import _http, edgar
from yquant.probes._frames import (
    frame_details,
    frame_head,
    frame_tail,
    json_safe,
    records,
    required_callable,
)
from yquant.probes.calendar import run_calendar_probe
from yquant.probes.models import (
    aggregate_status,
    make_probe_run,
    run_check,
    skipped_check,
    write_probe_run,
)
from yquant.probes.stooq import run_stooq_probe
from yquant.probes.yfinance_probe import run_yfinance_probe

# ---- _frames helpers -------------------------------------------------------

def test_json_safe_variants() -> None:
    assert json_safe(date(2024, 1, 2)) == "2024-01-02"
    assert json_safe(None) is None
    assert json_safe("x") == "x"
    assert json_safe(object()).startswith("<object")


def test_frame_helpers() -> None:
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    assert records(frame)[0] == {"a": 1, "b": "x"}
    assert len(frame_head(frame, 2)) == 2
    assert len(frame_tail(frame, 1)) == 1
    details = frame_details("fn", frame)
    assert details["rows"] == 3
    assert details["columns"] == ["a", "b"]


def test_required_callable_rejects_non_callable() -> None:
    module = types.ModuleType("m")
    module.thing = 5  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        required_callable(module, "thing")


# ---- models ----------------------------------------------------------------

def test_run_check_captures_success_and_failure() -> None:
    ok = run_check("ok", lambda: {"k": 1})
    assert ok.status == "passed" and ok.details == {"k": 1}

    def _boom() -> dict[str, Any]:
        raise RuntimeError("nope")

    bad = run_check("bad", _boom)
    assert bad.status == "failed"
    assert "RuntimeError" in (bad.error or "")


def test_aggregate_status() -> None:
    passed = run_check("a", lambda: {})
    skipped = skipped_check("b", "reason")
    assert aggregate_status([passed]) == "passed"
    assert aggregate_status([passed, skipped]) == "partial"
    assert aggregate_status([]) == "failed"


def test_write_probe_run_emits_json(tmp_path: Path) -> None:
    run = make_probe_run("demo", "2024-01-01T00:00:00+00:00", [run_check("a", lambda: {})])
    path = write_probe_run(run, tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip().startswith("{")


# ---- calendar probe (offline; pandas_market_calendars is a real dependency) --

def test_calendar_probe_runs_offline() -> None:
    run = run_calendar_probe(start="2024-01-02", end="2024-01-31")
    assert run.probe_name == "calendar"
    assert run.status in {"passed", "partial"}
    names = {check.name for check in run.checks}
    assert "import_pandas_market_calendars" in names


# ---- stooq / yfinance probes with injected fake modules --------------------

def test_stooq_probe_with_fake_module(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = pd.DataFrame(
        {"Close": [100.0, 102.0]},
        index=pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03"]), name="Date"),
    )
    pdr = types.ModuleType("pandas_datareader")
    pdr.__version__ = "0.10.0"  # type: ignore[attr-defined]
    pdr_data = types.ModuleType("pandas_datareader.data")
    pdr_data.DataReader = lambda *a, **k: frame  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pandas_datareader", pdr)
    monkeypatch.setitem(sys.modules, "pandas_datareader.data", pdr_data)

    run = run_stooq_probe(us_symbol="AAPL", index_symbol="^SPX")
    assert run.status in {"passed", "partial"}
    assert any(c.name == "us_daily_bars" and c.status == "passed" for c in run.checks)


def test_yfinance_probe_with_fake_module(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = pd.DataFrame(
        {"Close": [100.0]},
        index=pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]), name="Date"),
    )

    class _Ticker:
        def __init__(self, symbol: str) -> None:
            self.actions = pd.DataFrame(
                {"Dividends": [0.0]},
                index=pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]), name="Date"),
            )

    fake = types.ModuleType("yfinance")
    fake.__version__ = "0.2.40"  # type: ignore[attr-defined]
    fake.download = lambda *a, **k: bars  # type: ignore[attr-defined]
    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    run = run_yfinance_probe()
    assert run.status in {"passed", "partial"}
    assert any(c.name == "us_daily_bars" and c.status == "passed" for c in run.checks)


def test_probe_import_failure_yields_skipped_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def _fail(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pandas_datareader":
            raise ModuleNotFoundError("pandas_datareader")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", _fail)
    run = run_stooq_probe()
    statuses = {check.name: check.status for check in run.checks}
    assert statuses["import_pandas_datareader"] == "failed"
    assert statuses["us_daily_bars"] == "skipped"


# ---- edgar probe + http helpers (mocked fetch_json) ------------------------

def test_edgar_probe_with_mocked_fetch_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fetch(url: str, **kwargs: Any) -> Any:
        if "company_tickers" in url:
            return {"0": {"ticker": "AAPL", "cik_str": 320193}}
        if "submissions" in url:
            return {"name": "Apple Inc.", "filings": {"recent": {"form": ["8-K", "10-Q"]}}}
        return {"hits": {"hits": [{"a": 1}]}}

    monkeypatch.setattr(edgar, "fetch_json", _fake_fetch)
    run = edgar.run_edgar_probe(symbol="AAPL")
    statuses = {check.name: check.status for check in run.checks}
    assert statuses["ticker_cik_map"] == "passed"
    assert statuses["company_submissions"] == "passed"
    assert statuses["full_text_search"] == "passed"


def test_summarize_keys() -> None:
    assert _http.summarize_keys({"a": 1, "b": 2}) == ["a", "b"]
    assert _http.summarize_keys([1, 2, 3]) == []


def test_fetch_json_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        headers = types.SimpleNamespace(get_content_charset=lambda: "utf-8")

        def read(self) -> bytes:
            return b'{"ok": true}'

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(_http.urllib.request, "urlopen", lambda req, timeout: _Resp())
    payload = _http.fetch_json("https://example.test/x", params={"q": "1"})
    assert payload == {"ok": True}
