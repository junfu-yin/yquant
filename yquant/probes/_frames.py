"""Shared helpers for turning probe results into JSON-safe evidence."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any, cast


def json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def records(frame: Any) -> list[dict[str, Any]]:
    return [
        {str(key): json_safe(val) for key, val in record.items()}
        for record in frame.to_dict(orient="records")
    ]


def frame_head(frame: Any, rows: int = 3) -> list[dict[str, Any]]:
    return records(frame.head(rows))


def frame_tail(frame: Any, rows: int = 3) -> list[dict[str, Any]]:
    return records(frame.tail(rows))


def frame_details(function: str, frame: Any) -> dict[str, Any]:
    return {
        "function": function,
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "head": frame_head(frame),
    }


def required_callable(module: ModuleType, name: str) -> Callable[..., Any]:
    value = getattr(module, name)
    if not callable(value):
        raise TypeError(f"{module.__name__}.{name} is not callable")
    return cast(Callable[..., Any], value)
