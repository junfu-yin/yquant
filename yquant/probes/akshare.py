"""AkShare WP0 probe.

This module intentionally imports AkShare dynamically. A missing package is
probe evidence, not an import-time crash.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from types import ModuleType
from typing import Any, cast

from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso


def run_akshare_probe(symbol: str = "600000") -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []

    module_holder: dict[str, ModuleType] = {}

    def import_akshare() -> dict[str, Any]:
        module = importlib.import_module("akshare")
        module_holder["akshare"] = module
        return {
            "module": "akshare",
            "version": str(getattr(module, "__version__", "unknown")),
        }

    checks.append(run_check("import_akshare", import_akshare))
    akshare = module_holder.get("akshare")
    if akshare is None:
        checks.extend(
            [
                skipped_check("trade_calendar", "akshare import failed"),
                skipped_check("stock_list", "akshare import failed"),
                skipped_check("daily_bars", "akshare import failed"),
                skipped_check("announcement_function", "akshare import failed"),
            ]
        )
        return make_probe_run("akshare", started_at, checks)

    checks.append(run_check("trade_calendar", lambda: _probe_trade_calendar(akshare)))
    checks.append(run_check("stock_list", lambda: _probe_stock_list(akshare)))
    checks.append(run_check("daily_bars", lambda: _probe_daily_bars(akshare, symbol)))
    checks.append(run_check("announcement_function", lambda: _probe_announcement_function(akshare)))
    return make_probe_run("akshare", started_at, checks)


def _probe_trade_calendar(akshare: ModuleType) -> dict[str, Any]:
    fn = _required_callable(akshare, "tool_trade_date_hist_sina")
    frame = fn()
    return {
        "function": "tool_trade_date_hist_sina",
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": _frame_head(frame),
        "tail": _frame_tail(frame),
    }


def _probe_stock_list(akshare: ModuleType) -> dict[str, Any]:
    fn = _required_callable(akshare, "stock_info_a_code_name")
    frame = fn()
    return {
        "function": "stock_info_a_code_name",
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": _frame_head(frame),
    }


def _probe_daily_bars(akshare: ModuleType, symbol: str) -> dict[str, Any]:
    fn = _required_callable(akshare, "stock_zh_a_hist")
    frame = fn(
        symbol=symbol,
        period="daily",
        start_date="20240101",
        end_date="20240115",
        adjust="qfq",
    )
    return {
        "function": "stock_zh_a_hist",
        "symbol": symbol,
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": _frame_head(frame),
    }


def _probe_announcement_function(akshare: ModuleType) -> dict[str, Any]:
    fn = _required_callable(akshare, "stock_notice_report")
    signature = inspect.signature(fn)
    details: dict[str, Any] = {
        "function": "stock_notice_report",
        "signature": str(signature),
    }
    try:
        frame = fn(symbol="全部", date="20240102")
    except TypeError as exc:
        details["call_error"] = f"TypeError: {exc}"
        return details

    details.update(
        {
            "rows": int(len(frame)),
            "columns": [str(column) for column in frame.columns],
            "head": _frame_head(frame),
        }
    )
    return details


def _required_callable(module: ModuleType, name: str) -> Callable[..., Any]:
    value = getattr(module, name)
    if not callable(value):
        raise TypeError(f"akshare.{name} is not callable")
    return cast(Callable[..., Any], value)


def _frame_head(frame: Any, rows: int = 3) -> list[dict[str, Any]]:
    return _records(frame.head(rows))


def _frame_tail(frame: Any, rows: int = 3) -> list[dict[str, Any]]:
    return _records(frame.tail(rows))


def _records(frame: Any) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in record.items()}
        for record in frame.to_dict(orient="records")
    ]


def _json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)
