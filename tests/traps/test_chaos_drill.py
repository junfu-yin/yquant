"""WP8 monthly chaos-injection drill (06 §5): the job boundary degrades gracefully.

Loads ``scripts/chaos_drill.py`` by path and asserts every mandated fault
(source outage / API timeout / disk full / lock contention) is caught, ledgered
as an error, and alerted — never crashing the process.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "chaos_drill.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chaos_drill", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_chaos_drill_all_scenarios_degrade_gracefully() -> None:
    module = _load()
    assert module.main() == 0
    assert len(module.SCENARIOS) == 4
