"""BaoStock WP0 probe."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso


def run_baostock_probe(code: str = "sh.600000") -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []
    module_holder: dict[str, ModuleType] = {}

    def import_baostock() -> dict[str, Any]:
        module = importlib.import_module("baostock")
        module_holder["baostock"] = module
        return {
            "module": "baostock",
            "version": str(getattr(module, "__version__", "unknown")),
        }

    checks.append(run_check("import_baostock", import_baostock))
    baostock = module_holder.get("baostock")
    if baostock is None:
        checks.extend(
            [
                skipped_check("login", "baostock import failed"),
                skipped_check("trade_calendar", "baostock import failed"),
                skipped_check("stock_list", "baostock import failed"),
                skipped_check("daily_bars", "baostock import failed"),
            ]
        )
        return make_probe_run("baostock", started_at, checks)

    logged_in = False

    def login() -> dict[str, Any]:
        result = baostock.login()
        if getattr(result, "error_code", "") != "0":
            code = getattr(result, "error_code", "")
            message = getattr(result, "error_msg", "")
            raise RuntimeError(f"{code}: {message}")
        nonlocal logged_in
        logged_in = True
        return {
            "error_code": str(getattr(result, "error_code", "")),
            "error_msg": str(getattr(result, "error_msg", "")),
        }

    checks.append(run_check("login", login))
    if not logged_in:
        checks.extend(
            [
                skipped_check("trade_calendar", "baostock login failed"),
                skipped_check("stock_list", "baostock login failed"),
                skipped_check("daily_bars", "baostock login failed"),
            ]
        )
        return make_probe_run("baostock", started_at, checks)

    try:
        checks.append(run_check("trade_calendar", lambda: _probe_trade_calendar(baostock)))
        checks.append(run_check("stock_list", lambda: _probe_stock_list(baostock)))
        checks.append(run_check("daily_bars", lambda: _probe_daily_bars(baostock, code)))
    finally:
        baostock.logout()
    return make_probe_run("baostock", started_at, checks)


def _probe_trade_calendar(baostock: ModuleType) -> dict[str, Any]:
    result = baostock.query_trade_dates(start_date="2024-01-01", end_date="2024-01-31")
    rows = _collect_baostock_rows(result)
    return {
        "function": "query_trade_dates",
        "rows": len(rows),
        "fields": _fields(result),
        "head": rows[:3],
        "tail": rows[-3:],
    }


def _probe_stock_list(baostock: ModuleType) -> dict[str, Any]:
    result = baostock.query_all_stock(day="2024-01-02")
    rows = _collect_baostock_rows(result)
    return {
        "function": "query_all_stock",
        "rows": len(rows),
        "fields": _fields(result),
        "head": rows[:3],
    }


def _probe_daily_bars(baostock: ModuleType, code: str) -> dict[str, Any]:
    fields = "date,code,open,high,low,close,volume,amount,turn,pctChg,isST"
    result = baostock.query_history_k_data_plus(
        code,
        fields,
        start_date="2024-01-01",
        end_date="2024-01-15",
        frequency="d",
        adjustflag="2",
    )
    rows = _collect_baostock_rows(result)
    return {
        "function": "query_history_k_data_plus",
        "code": code,
        "rows": len(rows),
        "fields": _fields(result),
        "head": rows[:3],
    }


def _collect_baostock_rows(result: Any) -> list[dict[str, str]]:
    if getattr(result, "error_code", "") != "0":
        code = getattr(result, "error_code", "")
        message = getattr(result, "error_msg", "")
        raise RuntimeError(f"{code}: {message}")
    fields = _fields(result)
    rows: list[dict[str, str]] = []
    while result.next():
        rows.append(dict(zip(fields, result.get_row_data(), strict=True)))
    return rows


def _fields(result: Any) -> list[str]:
    return [str(field) for field in getattr(result, "fields", [])]
