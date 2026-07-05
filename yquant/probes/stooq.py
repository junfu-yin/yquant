"""Stooq WP0 probe (backup US/index daily-bar source via pandas-datareader).

Stooq provides free historical daily bars for US equities and indices. It is a
secondary source to fill yfinance gaps. Imported dynamically so a missing
package is probe evidence.
"""

from __future__ import annotations

import importlib
from datetime import date
from types import ModuleType
from typing import Any

from yquant.probes._frames import frame_head
from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso


def run_stooq_probe(us_symbol: str = "AAPL", index_symbol: str = "^SPX") -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []
    module_holder: dict[str, ModuleType] = {}

    def import_pandas_datareader() -> dict[str, Any]:
        module = importlib.import_module("pandas_datareader")
        module_holder["pdr"] = module
        return {
            "module": "pandas_datareader",
            "version": str(getattr(module, "__version__", "unknown")),
        }

    checks.append(run_check("import_pandas_datareader", import_pandas_datareader))
    pdr = module_holder.get("pdr")
    if pdr is None:
        checks.extend(
            [
                skipped_check("us_daily_bars", "pandas_datareader import failed"),
                skipped_check("index_bars", "pandas_datareader import failed"),
            ]
        )
        return make_probe_run("stooq", started_at, checks)

    checks.append(run_check("us_daily_bars", lambda: _probe_stooq(pdr, us_symbol)))
    checks.append(run_check("index_bars", lambda: _probe_stooq(pdr, index_symbol)))
    return make_probe_run("stooq", started_at, checks)


def _probe_stooq(pdr: ModuleType, symbol: str) -> dict[str, Any]:
    reader = importlib.import_module("pandas_datareader.data")
    frame = reader.DataReader(
        symbol,
        "stooq",
        start=date(2024, 1, 1),
        end=date(2024, 1, 15),
    )
    frame = frame.reset_index()
    frame.columns = [str(column) for column in frame.columns]
    return {
        "function": "DataReader(symbol, 'stooq')",
        "symbol": symbol,
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": frame_head(frame),
    }
