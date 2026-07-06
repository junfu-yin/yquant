"""yfinance WP0 probe (primary US market-data source).

Imports yfinance dynamically: a missing package is probe evidence, not an
import-time crash. Verifies daily bars, split/dividend actions, and index data
for US symbols. Network flakiness is expected; each check captures its own
failure.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from yquant.probes._frames import frame_head, required_callable
from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso


def run_yfinance_probe(
    us_symbol: str = "AAPL",
    index_symbol: str = "^GSPC",
) -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []
    module_holder: dict[str, ModuleType] = {}

    def import_yfinance() -> dict[str, Any]:
        module = importlib.import_module("yfinance")
        module_holder["yfinance"] = module
        return {
            "module": "yfinance",
            "version": str(getattr(module, "__version__", "unknown")),
        }

    checks.append(run_check("import_yfinance", import_yfinance))
    yfinance = module_holder.get("yfinance")
    if yfinance is None:
        checks.extend(
            [
                skipped_check("us_daily_bars", "yfinance import failed"),
                skipped_check("split_dividend_actions", "yfinance import failed"),
                skipped_check("index_bars", "yfinance import failed"),
            ]
        )
        return make_probe_run("yfinance", started_at, checks)

    checks.append(run_check("us_daily_bars", lambda: _probe_daily_bars(yfinance, us_symbol)))
    checks.append(
        run_check("split_dividend_actions", lambda: _probe_actions(yfinance, us_symbol))
    )
    checks.append(run_check("index_bars", lambda: _probe_daily_bars(yfinance, index_symbol)))
    return make_probe_run("yfinance", started_at, checks)


def _probe_daily_bars(yfinance: ModuleType, symbol: str) -> dict[str, Any]:
    download = required_callable(yfinance, "download")
    frame = download(
        symbol,
        start="2024-01-01",
        end="2024-01-15",
        auto_adjust=True,
        progress=False,
    )
    frame = frame.reset_index()
    frame.columns = [_flatten_column(column) for column in frame.columns]
    return {
        "function": "download(auto_adjust=True)",
        "symbol": symbol,
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": frame_head(frame),
    }


def _flatten_column(column: Any) -> str:
    if isinstance(column, tuple):
        return "_".join(str(part) for part in column if str(part))
    return str(column)


def _probe_actions(yfinance: ModuleType, symbol: str) -> dict[str, Any]:
    ticker = required_callable(yfinance, "Ticker")(symbol)
    actions = ticker.actions
    actions = actions.reset_index()
    actions.columns = [str(column) for column in actions.columns]
    return {
        "attribute": "Ticker(symbol).actions",
        "symbol": symbol,
        "rows": int(len(actions)),
        "columns": [str(column) for column in actions.columns],
        "head": frame_head(actions),
    }
