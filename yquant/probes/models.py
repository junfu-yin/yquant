"""Structured evidence model for WP0 probes."""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

CheckStatus = Literal["passed", "failed", "skipped"]
ProbeStatus = Literal["passed", "partial", "failed"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ProbeRun:
    probe_name: str
    status: ProbeStatus
    started_at: str
    ended_at: str
    environment: dict[str, str]
    checks: list[CheckResult]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def probe_environment() -> dict[str, str]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
    }


def run_check(name: str, fn: Callable[[], dict[str, Any]]) -> CheckResult:
    started = perf_counter()
    try:
        details = fn()
    except Exception as exc:  # noqa: BLE001 - probe evidence must capture unexpected failures.
        return CheckResult(
            name=name,
            status="failed",
            duration_seconds=round(perf_counter() - started, 6),
            error=f"{type(exc).__name__}: {exc}",
        )
    return CheckResult(
        name=name,
        status="passed",
        duration_seconds=round(perf_counter() - started, 6),
        details=details,
    )


def skipped_check(name: str, reason: str) -> CheckResult:
    return CheckResult(name=name, status="skipped", duration_seconds=0.0, error=reason)


def aggregate_status(checks: list[CheckResult]) -> ProbeStatus:
    if not checks or all(check.status == "failed" for check in checks):
        return "failed"
    if any(check.status in {"failed", "skipped"} for check in checks):
        return "partial"
    return "passed"


def make_probe_run(probe_name: str, started_at: str, checks: list[CheckResult]) -> ProbeRun:
    return ProbeRun(
        probe_name=probe_name,
        status=aggregate_status(checks),
        started_at=started_at,
        ended_at=utc_now_iso(),
        environment=probe_environment(),
        checks=checks,
    )


def write_probe_run(run: ProbeRun, output_dir: str | Path) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{timestamp}_{run.probe_name}.json"
    fd, raw_temp_path = tempfile.mkstemp(
        dir=directory,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temp_path = Path(raw_temp_path)
    try:
        temp_path.write_text(
            json.dumps(asdict(run), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path
