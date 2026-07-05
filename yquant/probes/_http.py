"""Shared HTTP helpers for announcement probes (EDGAR / HKEXnews).

These sources are official HTTP/JSON endpoints, not pip packages, so the probe
pattern here is "reachability + response shape" rather than "dynamic import".
Uses only the standard library so a missing third-party package can never break
these probes. Every request carries a timeout; callers wrap results in
``run_check`` so a network failure becomes evidence, not a crash.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# SEC EDGAR fair-access policy requires a descriptive User-Agent (see docs §11).
DEFAULT_USER_AGENT = "yquant-research probe (contact: set YQUANT_SEC_USER_AGENT)"


def fetch_json(
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - trusted official hosts
        charset = response.headers.get_content_charset() or "utf-8"
        payload = response.read().decode(charset)
    return json.loads(payload)


def summarize_keys(payload: Any, limit: int = 20) -> list[str]:
    if isinstance(payload, dict):
        return [str(key) for key in list(payload.keys())[:limit]]
    return []
