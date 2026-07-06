"""JSON artifact helpers for M1 data-quality evidence."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast


def write_report_artifact(
    report: object,
    output_dir: str | Path,
    *,
    kind: str,
    generated_at_utc: datetime | None = None,
) -> Path:
    """Persist a report object as a timestamped JSON artifact."""

    generated_at = _aware_utc(generated_at_utc or datetime.now(UTC))
    normalized_kind = _normalize_kind(kind)
    output_path = Path(output_dir) / f"{_timestamp_for_path(generated_at)}_{normalized_kind}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": normalized_kind,
        "generated_at_utc": generated_at.isoformat(),
        "report": _report_payload(report),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def read_report_artifact(path: str | Path) -> dict[str, Any]:
    """Read a JSON artifact written by :func:`write_report_artifact`."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact root must be a JSON object: {path}")
    return cast(dict[str, Any], payload)


def json_safe(value: Any) -> Any:
    """Convert dataclasses, dates, tuples, and dicts into JSON-safe values."""

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: json_safe(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, datetime):
        return _aware_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(val) for key, val in value.items()}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _report_payload(report: object) -> dict[str, Any]:
    payload = json_safe(report)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    for attr in ("passed", "consistency_rate", "succeeded_symbols"):
        if hasattr(report, attr):
            payload[attr] = json_safe(getattr(report, attr))
    return payload


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp_for_path(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def _normalize_kind(kind: str) -> str:
    normalized = kind.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        raise ValueError("artifact kind must not be empty")
    return normalized
