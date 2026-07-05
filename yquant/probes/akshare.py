"""AkShare WP0 probe (backup US/HK market-data source).

AkShare is the backup daily-bar and stock-list source for US and HK equities
(yfinance is primary). Imported dynamically so a missing package is probe
evidence, not an import-time crash. Network flakiness is expected; each check
captures its own failure.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from yquant.probes._frames import frame_details, frame_head, required_callable
from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso


def run_akshare_probe(us_symbol: str = "AAPL", hk_symbol: str = "00700") -> Any:
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
                skipped_check("us_daily_bars", "akshare import failed"),
                skipped_check("hk_daily_bars", "akshare import failed"),
                skipped_check("us_stock_list", "akshare import failed"),
                skipped_check("hk_stock_list", "akshare import failed"),
            ]
        )
        return make_probe_run("akshare", started_at, checks)

    checks.append(run_check("us_daily_bars", lambda: _probe_us_daily(akshare, us_symbol)))
    checks.append(run_check("hk_daily_bars", lambda: _probe_hk_daily(akshare, hk_symbol)))
    checks.append(run_check("us_stock_list", lambda: _probe_us_stock_list(akshare)))
    checks.append(run_check("hk_stock_list", lambda: _probe_hk_stock_list(akshare)))
    return make_probe_run("akshare", started_at, checks)


def _probe_us_daily(akshare: ModuleType, symbol: str) -> dict[str, Any]:
    frame = required_callable(akshare, "stock_us_daily")(symbol=symbol, adjust="qfq")
    details = frame_details("stock_us_daily", frame)
    details["symbol"] = symbol
    return details


def _probe_hk_daily(akshare: ModuleType, symbol: str) -> dict[str, Any]:
    frame = required_callable(akshare, "stock_hk_daily")(symbol=symbol, adjust="")
    details = frame_details("stock_hk_daily", frame)
    details["symbol"] = symbol
    return details


def _probe_us_stock_list(akshare: ModuleType) -> dict[str, Any]:
    frame = required_callable(akshare, "stock_us_spot_em")()
    return {
        "function": "stock_us_spot_em",
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": frame_head(frame),
    }


def _probe_hk_stock_list(akshare: ModuleType) -> dict[str, Any]:
    frame = required_callable(akshare, "stock_hk_spot_em")()
    return {
        "function": "stock_hk_spot_em",
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": frame_head(frame),
    }
