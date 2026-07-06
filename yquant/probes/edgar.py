"""SEC EDGAR WP0 probe (US announcement source).

EDGAR is the primary US announcement source (8-K/10-Q/10-K/Form 4 ...). This
probe checks the three official endpoints the M1 adapter will rely on:
  1. ticker -> CIK map            (www.sec.gov/files/company_tickers.json)
  2. per-company filing feed      (data.sec.gov/submissions/CIK##########.json)
  3. full-text search             (efts.sec.gov/LATEST/search-index)

SEC fair-access policy requires a descriptive User-Agent and rate limiting;
the adapter must honor both. Set ``YQUANT_SEC_USER_AGENT`` to a real contact.
Network/policy failures are captured as evidence, never raised.
"""

from __future__ import annotations

import os
from typing import Any

from yquant.probes._http import DEFAULT_USER_AGENT, fetch_json, summarize_keys
from yquant.probes.models import CheckResult, make_probe_run, run_check, skipped_check, utc_now_iso

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


def run_edgar_probe(symbol: str = "AAPL", user_agent: str | None = None) -> Any:
    started_at = utc_now_iso()
    checks: list[CheckResult] = []
    sec_user_agent = user_agent or os.getenv("YQUANT_SEC_USER_AGENT") or DEFAULT_USER_AGENT
    headers: dict[str, str] = {"User-Agent": sec_user_agent}
    cik_holder: dict[str, str] = {}

    def resolve_cik() -> dict[str, Any]:
        payload = fetch_json(_TICKER_MAP_URL, headers=headers)
        cik = _find_cik(payload, symbol)
        if cik is None:
            raise LookupError(f"ticker {symbol!r} not found in company_tickers.json")
        cik_holder["cik"] = cik
        return {"url": _TICKER_MAP_URL, "symbol": symbol, "cik": cik, "entries": len(payload)}

    checks.append(run_check("ticker_cik_map", resolve_cik))
    cik = cik_holder.get("cik")
    if cik is None:
        checks.append(skipped_check("company_submissions", "cik resolution failed"))
    else:
        checks.append(
            run_check("company_submissions", lambda: _probe_submissions(cik, headers))
        )

    checks.append(run_check("full_text_search", lambda: _probe_full_text_search(symbol, headers)))
    return make_probe_run("edgar", started_at, checks)


def _find_cik(payload: Any, symbol: str) -> str | None:
    target = symbol.upper()
    records = payload.values() if isinstance(payload, dict) else payload
    for record in records:
        if str(record.get("ticker", "")).upper() == target:
            return f"{int(record['cik_str']):010d}"
    return None


def _probe_submissions(cik: str, headers: dict[str, str]) -> dict[str, Any]:
    url = _SUBMISSIONS_URL.format(cik=cik)
    payload = fetch_json(url, headers=headers)
    recent = payload.get("filings", {}).get("recent", {})
    return {
        "url": url,
        "name": payload.get("name"),
        "top_level_keys": summarize_keys(payload),
        "recent_filing_columns": summarize_keys(recent),
        "recent_filing_count": len(recent.get("form", [])),
        "sample_forms": recent.get("form", [])[:5],
    }


def _probe_full_text_search(symbol: str, headers: dict[str, str]) -> dict[str, Any]:
    params = {"q": symbol, "forms": "8-K"}
    payload = fetch_json(_FULL_TEXT_SEARCH_URL, params=params, headers=headers)
    hits = payload.get("hits", {}).get("hits", []) if isinstance(payload, dict) else []
    return {
        "url": _FULL_TEXT_SEARCH_URL,
        "query": params,
        "top_level_keys": summarize_keys(payload),
        "hit_count": len(hits),
    }
