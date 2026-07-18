#!/usr/bin/env python3
"""Deterministic mutation check for core safety-critical logic.

A lightweight alternative to a full mutmut campaign (whose environment model is
awkward in this repo). For each curated mutation we patch the source, run the
targeted tests, and require them to FAIL — a surviving mutant means the tests do
not actually pin that behaviour. Exits non-zero if any mutant survives.

Run: ``python scripts/mutation_check.py``
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent


def _clear_pycache(root: Path) -> None:
    """Remove cached bytecode so no stale .pyc can shadow a (re)written source.

    Rewriting a source in the same wall-clock second as an existing .pyc can make
    CPython load the stale bytecode; clearing caches and disabling .pyc writes in
    the test subprocesses makes each run compile from the current source.
    """

    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


@dataclass(frozen=True)
class Mutation:
    module: str
    tests: list[str]
    old: str
    new: str
    label: str


# Each mutation represents a plausible bug the tests must catch.
MUTATIONS: list[Mutation] = [
    Mutation(
        "yquant/datasrc/retry.py",
        ["tests/unit/test_datasrc_retry.py"],
        "if attempt >= policy.max_attempts:",
        "if attempt > policy.max_attempts:",
        "retry: off-by-one on attempt exhaustion",
    ),
    Mutation(
        "yquant/datasrc/retry.py",
        ["tests/unit/test_datasrc_retry.py"],
        "return min(delay, self.max_delay_seconds)",
        "return max(delay, self.max_delay_seconds)",
        "retry: delay cap direction",
    ),
    Mutation(
        "yquant/datasrc/retry.py",
        ["tests/unit/test_datasrc_retry.py", "tests/unit/test_property_invariants.py"],
        "delay = self.base_delay_seconds * (self.backoff_factor ** (attempt - 1))",
        "delay = self.base_delay_seconds * (self.backoff_factor ** (attempt + 1))",
        "retry: backoff exponent",
    ),
    Mutation(
        "yquant/risk/regime.py",
        ["tests/unit/test_risk_regime.py", "tests/unit/test_overlay_dynamic_gate.py"],
        "if not market_trend_ok:",
        "if market_trend_ok:",
        "regime: trend gate inverted",
    ),
    Mutation(
        "yquant/risk/regime.py",
        ["tests/unit/test_risk_regime.py"],
        "if vix_level is not None and vix_level > vix_threshold:",
        "if vix_level is not None and vix_level < vix_threshold:",
        "regime: vix comparison inverted",
    ),
    Mutation(
        "yquant/datasrc/reconcile.py",
        ["tests/unit/test_datasrc_update.py", "tests/unit/test_property_invariants.py"],
        "return matching_rows / total_rows",
        "return (matching_rows + len(self.mismatches)) / total_rows",
        "reconcile: consistency numerator sign",
    ),
    Mutation(
        "yquant/datasrc/reconcile.py",
        ["tests/unit/test_datasrc_update.py"],
        "return self.compared_rows > 0 and self.consistency_rate >= self.minimum_consistency_rate",
        "return self.compared_rows > 0 and self.consistency_rate <= self.minimum_consistency_rate",
        "reconcile: pass threshold direction",
    ),
    Mutation(
        "yquant/discipline/overlay_guardrails.py",
        ["tests/unit/test_redlines.py"],
        "if exposure.overlay_weight_after > config.overlay_cap:",
        "if exposure.overlay_weight_after > config.overlay_cap + 1.0:",
        "redline R1: overlay 10% cap weakened",
    ),
    Mutation(
        "yquant/overlay/leverage.py",
        ["tests/unit/test_redlines.py"],
        "if regime is not RegimeState.RISK_ON:\n        failed.append(\"regime_not_risk_on\")",
        "if False:\n        failed.append(\"regime_not_risk_on\")",
        "redline R2: 2x regime condition dropped",
    ),
    Mutation(
        "yquant/risk/regime_gate.py",
        ["tests/unit/test_redlines.py"],
        "RegimeState.CRISIS: 0.0,",
        "RegimeState.CRISIS: 1.0,",
        "redline R4: crisis stops clearing overlay",
    ),
    Mutation(
        "yquant/backtest/report.py",
        ["tests/unit/test_backtest_report.py", "tests/traps/test_t0_backtest_smoke.py"],
        "providers = _fresh_providers(target_provider_factory, len(_COST_TIERS))",
        "providers = [target_provider_factory()] * len(_COST_TIERS)",
        "report: cost tiers reuse stateful provider",
    ),
    Mutation(
        "yquant/discipline/proposals.py",
        ["tests/unit/test_discipline.py", "tests/unit/test_property_invariants.py"],
        "trade_value = abs(delta) * portfolio_value",
        "trade_value = target * portfolio_value",
        "proposal: target shares replace incremental shares",
    ),
]


def _run_tests(root: Path, tests: list[str]) -> Literal["passed", "failed", "timeout"]:
    """Return the targeted test outcome for one isolated mutation."""

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-x", "-q", "-p", "no:cov", *tests],
            cwd=root,
            capture_output=True,
            env={**env, "PYTHONPATH": str(root)},
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    return "passed" if result.returncode == 0 else "failed"


def _copy_workspace(destination: Path) -> None:
    """Copy only files needed by mutation tests into an isolated workspace."""

    for directory in ("yquant", "tests"):
        shutil.copytree(
            ROOT / directory,
            destination / directory,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for filename in ("config.example.toml", "pyproject.toml"):
        shutil.copy2(ROOT / filename, destination / filename)


def main() -> int:
    survivors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="yquant-mutation-") as raw_temp:
        workspace = Path(raw_temp)
        _copy_workspace(workspace)
        for mutation in MUTATIONS:
            path = workspace / mutation.module
            original = path.read_text(encoding="utf-8")
            if mutation.old not in original:
                print(f"SKIP (anchor not found): {mutation.label}")
                survivors.append(f"{mutation.label} [anchor missing]")
                continue
            path.write_text(original.replace(mutation.old, mutation.new, 1), encoding="utf-8")
            _clear_pycache(workspace)
            try:
                outcome = _run_tests(workspace, mutation.tests)
            finally:
                path.write_text(original, encoding="utf-8")
            if outcome == "passed":
                print(f"SURVIVED: {mutation.label}")
                survivors.append(mutation.label)
            elif outcome == "timeout":
                print(f"TIMEOUT:  {mutation.label}")
                survivors.append(f"{mutation.label} [test timeout]")
            else:
                print(f"killed:   {mutation.label}")

    print(f"\n{len(MUTATIONS) - len(survivors)}/{len(MUTATIONS)} mutants killed")
    if survivors:
        print("Surviving mutants (tests do not pin this behaviour):")
        for survivor in survivors:
            print(f"  - {survivor}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
