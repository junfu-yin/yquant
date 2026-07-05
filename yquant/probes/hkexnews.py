"""HKEXnews WP0 probe (HK announcement source).

披露易 HKEXnews is the primary HK announcement source (业绩/须予公布交易/配售/
回购 ...). The public title-search servlet returns JSON describing filings for a
stock. This probe checks reachability and the response shape the M1 adapter will
parse. HK filings are frequently PDFs (正文 availability is an open AS-1
question), so the probe records the document metadata, not body text.

Network/servlet-format failures are captured as evidence, never raised.
"""

from __future__ import annotations

import json
from typing import Any

from yquant.probes._http import fetch_json, summarize_keys
from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso

_TITLE_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"

# HKEXnews groups markets by "MB" (main board) / "GEM"; SEHK stock id is the
# zero-padded numeric code without the ".HK" suffix used elsewhere in yquant.
_DEFAULT_PARAMS = {
    "sortDir": "0",
    "sortByOptions": "DateTime",
    "category": "0",
    "market": "SEHK",
    "documentType": "-1",
    "t1code": "-2",
    "t2Gcode": "-2",
    "t2code": "-2",
    "searchType": "1",
    "lang": "EN",
}


def run_hkexnews_probe(symbol: str = "0700.HK") -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []

    stock_id = _to_stock_id(symbol)
    if stock_id is None:
        checks.append(skipped_check("title_search", f"cannot derive SEHK id from {symbol!r}"))
        return make_probe_run("hkexnews", started_at, checks)

    checks.append(run_check("title_search", lambda: _probe_title_search(symbol, stock_id)))
    return make_probe_run("hkexnews", started_at, checks)


def _to_stock_id(symbol: str) -> str | None:
    digits = symbol.split(".")[0].strip()
    if not digits.isdigit():
        return None
    return digits.zfill(5)


def _probe_title_search(symbol: str, stock_id: str) -> dict[str, Any]:
    params = {**_DEFAULT_PARAMS, "stockId": stock_id}
    payload = fetch_json(_TITLE_SEARCH_URL, params=params)
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = json.loads(result) if isinstance(result, str) else result
    rows = rows if isinstance(rows, list) else []
    return {
        "url": _TITLE_SEARCH_URL,
        "symbol": symbol,
        "stock_id": stock_id,
        "top_level_keys": summarize_keys(payload),
        "row_count": len(rows),
        "row_columns": summarize_keys(rows[0]) if rows else [],
    }
