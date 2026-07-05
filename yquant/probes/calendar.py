"""Trading-calendar WP0 probe (pandas_market_calendars).

The M7 scheduler and M1 quality checks need trading calendars for NYSE, NASDAQ
and HKEX, including US daylight-saving shifts, half-days and HK typhoon/black-
rain closures. This probe confirms ``pandas_market_calendars`` exposes each
market and returns a non-empty schedule. Imported dynamically so a missing
package is probe evidence, not an import-time crash.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso

_MARKETS = {"us_nyse": "NYSE", "us_nasdaq": "NASDAQ", "hk": "HKEX"}


def run_calendar_probe(start: str = "2024-01-01", end: str = "2024-01-31") -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []
    module_holder: dict[str, ModuleType] = {}

    def import_calendars() -> dict[str, Any]:
        module = importlib.import_module("pandas_market_calendars")
        module_holder["mcal"] = module
        return {
            "module": "pandas_market_calendars",
            "version": str(getattr(module, "__version__", "unknown")),
            "available": len(getattr(module, "get_calendar_names", lambda: [])()),
        }

    checks.append(run_check("import_pandas_market_calendars", import_calendars))
    mcal = module_holder.get("mcal")
    if mcal is None:
        checks.extend(
            skipped_check(name, "pandas_market_calendars import failed") for name in _MARKETS
        )
        return make_probe_run("calendar", started_at, checks)

    for name, exchange in _MARKETS.items():
        checks.append(
            run_check(name, lambda exchange=exchange: _probe_schedule(mcal, exchange, start, end))
        )
    return make_probe_run("calendar", started_at, checks)


def _probe_schedule(mcal: ModuleType, exchange: str, start: str, end: str) -> dict[str, Any]:
    calendar = mcal.get_calendar(exchange)
    schedule = calendar.schedule(start_date=start, end_date=end)
    return {
        "exchange": exchange,
        "name": getattr(calendar, "name", exchange),
        "tz": str(getattr(calendar, "tz", "unknown")),
        "session_count": int(len(schedule)),
        "columns": [str(column) for column in schedule.columns],
        "first_session": str(schedule.index[0]) if len(schedule) else None,
        "last_session": str(schedule.index[-1]) if len(schedule) else None,
    }
