"""Tushare Pro WP0 probe."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from types import ModuleType
from typing import Any, cast

from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso


def run_tushare_probe(ts_code: str = "600000.SH", token_env: str = "YQUANT_TUSHARE_TOKEN") -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []
    module_holder: dict[str, ModuleType] = {}
    client_holder: dict[str, Any] = {}

    def import_tushare() -> dict[str, Any]:
        module = importlib.import_module("tushare")
        module_holder["tushare"] = module
        return {
            "module": "tushare",
            "version": str(getattr(module, "__version__", "unknown")),
        }

    checks.append(run_check("import_tushare", import_tushare))
    tushare = module_holder.get("tushare")
    if tushare is None:
        checks.extend(_skipped_without_package())
        return make_probe_run("tushare", started_at, checks)

    token = os.getenv(token_env)
    if not token:
        checks.append(skipped_check("create_pro_client", f"missing env var: {token_env}"))
        checks.extend(_skipped_without_client())
        return make_probe_run("tushare", started_at, checks)

    def create_pro_client() -> dict[str, Any]:
        pro_api = _required_callable(tushare, "pro_api")
        client_holder["pro"] = pro_api(token)
        return {"token_env": token_env, "token_present": True}

    checks.append(run_check("create_pro_client", create_pro_client))
    pro = client_holder.get("pro")
    if pro is None:
        checks.extend(_skipped_without_client())
        return make_probe_run("tushare", started_at, checks)

    checks.append(run_check("trade_calendar", lambda: _probe_trade_calendar(pro)))
    checks.append(run_check("stock_basic", lambda: _probe_stock_basic(pro)))
    checks.append(run_check("daily_bars", lambda: _probe_daily_bars(pro, ts_code)))
    checks.append(
        run_check("financial_announce_date", lambda: _probe_financial_announce_date(pro, ts_code))
    )
    checks.append(run_check("announcement_function", lambda: _probe_announcement_function(pro)))
    return make_probe_run("tushare", started_at, checks)


def _probe_trade_calendar(pro: Any) -> dict[str, Any]:
    frame = pro.trade_cal(exchange="", start_date="20240101", end_date="20240131")
    return _frame_details("trade_cal", frame)


def _probe_stock_basic(pro: Any) -> dict[str, Any]:
    frame = pro.stock_basic(
        exchange="",
        list_status="L,D,P",
        fields="ts_code,symbol,name,area,industry,list_date,delist_date",
    )
    return _frame_details("stock_basic", frame)


def _probe_daily_bars(pro: Any, ts_code: str) -> dict[str, Any]:
    frame = pro.daily(ts_code=ts_code, start_date="20240101", end_date="20240115")
    details = _frame_details("daily", frame)
    details["ts_code"] = ts_code
    return details


def _probe_financial_announce_date(pro: Any, ts_code: str) -> dict[str, Any]:
    frame = pro.income(
        ts_code=ts_code,
        start_date="20230101",
        end_date="20240131",
        fields="ts_code,ann_date,f_ann_date,end_date,revenue,n_income_attr_p",
    )
    details = _frame_details("income", frame)
    details["ts_code"] = ts_code
    details["has_ann_date"] = "ann_date" in [str(column) for column in frame.columns]
    return details


def _probe_announcement_function(pro: Any) -> dict[str, Any]:
    if not hasattr(pro, "anns_d"):
        return {"function": "anns_d", "available": False}
    frame = pro.anns_d(ann_date="20240102")
    details = _frame_details("anns_d", frame)
    details["available"] = True
    return details


def _frame_details(function: str, frame: Any) -> dict[str, Any]:
    return {
        "function": function,
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": _records(frame.head(3)),
    }


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


def _required_callable(module: ModuleType, name: str) -> Callable[..., Any]:
    value = getattr(module, name)
    if not callable(value):
        raise TypeError(f"tushare.{name} is not callable")
    return cast(Callable[..., Any], value)


def _skipped_without_package() -> list[CheckResult]:
    return [
        skipped_check("create_pro_client", "tushare import failed"),
        *_skipped_without_client(),
    ]


def _skipped_without_client() -> list[CheckResult]:
    return [
        skipped_check("trade_calendar", "tushare pro client unavailable"),
        skipped_check("stock_basic", "tushare pro client unavailable"),
        skipped_check("daily_bars", "tushare pro client unavailable"),
        skipped_check("financial_announce_date", "tushare pro client unavailable"),
        skipped_check("announcement_function", "tushare pro client unavailable"),
    ]
