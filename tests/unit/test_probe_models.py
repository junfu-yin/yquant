import json

from yquant.probes.models import (
    CheckResult,
    aggregate_status,
    make_probe_run,
    write_probe_run,
)


def test_aggregate_status() -> None:
    assert aggregate_status([CheckResult("a", "passed", 0.1)]) == "passed"
    assert aggregate_status([CheckResult("a", "passed", 0.1), CheckResult("b", "skipped", 0)]) == (
        "partial"
    )
    assert aggregate_status([CheckResult("a", "failed", 0.1, error="x")]) == "failed"


def test_write_probe_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    run = make_probe_run("sample", "2026-07-05T00:00:00+00:00", [CheckResult("a", "passed", 0.1)])

    path = write_probe_run(run, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["probe_name"] == "sample"
    assert payload["status"] == "passed"
    assert payload["checks"][0]["name"] == "a"

