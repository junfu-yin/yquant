"""Unit tests for the WP11 operations layer (runbook / interval-book / daily-check).

The plan's WP11 exit gate is "四场景演习台账 + 委托人独立完成一次日检"; the drill
ledger already lives in :mod:`yquant.qa.drills`, so these tests pin the three
run-the-thing deliverables that make the check *evidence* rather than prose:
the machine-readable runbook every alert binds to, the layered pre-registered
interval book, and the owner's deterministic five-minute day-check.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from yquant.notify.graded import FIXED_SOURCES
from yquant.ops import (
    IntervalBand,
    build_daily_check,
    build_interval_book,
    build_runbook,
)
from yquant.ops.daily_check import DailyCheck
from yquant.ops.interval_book import bands_from_oos
from yquant.ops.interval_book_demo import build_demo_bars, build_demo_interval_book
from yquant.ops.runbook import alert_binding_gaps

# ---------------------------------------------------------------- runbook ---


def test_runbook_binds_every_alert_source() -> None:
    """The "告警 → runbook 段落" loop must close: no dangling references."""

    assert alert_binding_gaps() == []


def test_runbook_covers_every_fixed_source_ref() -> None:
    runbook = build_runbook()
    refs = runbook.refs()
    for _, ref in FIXED_SOURCES.values():
        assert ref in refs
    assert "runbook §6.1" in refs  # the AlertRouter default-source fallback.


def test_runbook_section_lookup_and_serialisation() -> None:
    runbook = build_runbook()
    section = runbook.section("runbook §6.3")
    assert section is not None
    assert section.severity_hint == "S1"
    assert section.steps  # actionable, not empty.
    payload = section.as_dict()
    assert payload["ref"] == "runbook §6.3"
    assert isinstance(payload["steps"], list)
    assert runbook.section("runbook §nope") is None


def test_runbook_as_dict_round_trips_all_sections() -> None:
    runbook = build_runbook()
    payload = runbook.as_dict()
    assert {s["ref"] for s in payload["sections"]} == runbook.refs()


def test_alert_binding_gaps_flags_missing_section() -> None:
    """A pruned runbook must be reported as having a gap (guards the guard)."""

    runbook = build_runbook()
    trimmed = type(runbook)(
        sections=tuple(s for s in runbook.sections if s.ref != "runbook §6.3")
    )
    assert "runbook §6.3" in alert_binding_gaps(trimmed)


# --------------------------------------------------------- interval-book ---


def test_bands_from_oos_returns_empty_without_windows() -> None:
    assert bands_from_oos({"num_windows": 0, "windows": []}) == ()


def test_bands_from_oos_builds_two_bands_from_percentiles() -> None:
    summary: dict[str, Any] = {
        "num_windows": 3,
        "annualized_return_pctile": {"p10": 0.01, "p50": 0.05, "p90": 0.12},
        "max_drawdown_pctile": {"p10": 0.02, "p50": 0.04, "p90": 0.08},
    }
    bands = bands_from_oos(summary)
    assert [b.metric for b in bands] == ["annualized_return", "max_drawdown"]
    assert bands[0].p50 == 0.05


def test_build_interval_book_has_four_layers_with_honest_kinds() -> None:
    bars = build_demo_bars()
    book = build_interval_book(bars, as_of=date(2025, 1, 1))
    assert book.num_oos_windows > 0

    core = book.layer("core")
    assert core is not None and core.kind == "numeric"
    assert len(core.bands) == 2  # the OOS-derived return + drawdown bands.

    satellite_rule = book.layer("satellite_rule")
    assert satellite_rule is not None and satellite_rule.kind == "numeric"
    assert len(satellite_rule.bands) == 2
    assert satellite_rule.hard_caps["single_name"] == 0.05
    assert satellite_rule.bands != core.bands

    satellite_llm = book.layer("satellite_llm")
    assert satellite_llm is not None
    assert satellite_llm.kind == "observing"  # forward-unknown: no numeric band.
    assert satellite_llm.bands == ()
    assert satellite_llm.hard_caps == {"s_b_cap": 0.10, "s_c_cap": 0.05}

    overlay = book.layer("overlay")
    assert overlay is not None and overlay.kind == "observing"
    assert overlay.hard_caps["overlay_total"] == 0.10
    assert overlay.hard_caps["leveraged_2x_total"] == 0.05


def test_build_interval_book_missing_layer_returns_none() -> None:
    book = build_interval_book(build_demo_bars(), as_of=date(2025, 1, 1))
    assert book.layer("does_not_exist") is None


def test_interval_book_as_dict_is_json_safe() -> None:
    book = build_demo_interval_book()
    payload = book.as_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False))["version"] == "v1"
    assert payload["num_oos_windows"] == book.num_oos_windows


def test_interval_band_rounds_on_serialisation() -> None:
    band = IntervalBand("annualized_return", 0.1234567, 0.2, 0.3)
    assert band.as_dict()["p10"] == 0.123457


def test_demo_interval_book_is_deterministic() -> None:
    first = build_demo_interval_book().as_dict()
    second = build_demo_interval_book().as_dict()
    assert first == second


# ----------------------------------------------------------- daily-check ---


def test_daily_check_default_payload_flags_sentinel() -> None:
    """The demo payload has an invalidated thesis (SMH), so it is not all-clear."""

    check = build_daily_check()
    assert isinstance(check, DailyCheck)
    assert not check.all_clear
    attention = {item.key for item in check.attention_items}
    assert "thesis_sentinel" in attention
    sentinel = next(i for i in check.items if i.key == "thesis_sentinel")
    assert sentinel.runbook_ref == "runbook §6.4"


def test_daily_check_does_not_replace_explicit_empty_payload_with_demo() -> None:
    with pytest.raises(KeyError):
        build_daily_check({})


def test_daily_check_all_clear_on_benign_payload() -> None:
    check = build_daily_check(_benign_payload())
    assert check.all_clear
    assert check.attention_items == ()
    assert all(item.runbook_ref is None for item in check.items)


def test_daily_check_fails_closed_on_empty_health_maps() -> None:
    payload = _benign_payload()
    payload["system_health"] = {"data_freshness": {}, "p_metrics": {}}

    attention = {item.key for item in build_daily_check(payload).attention_items}

    assert {"data_freshness", "p_metrics"} <= attention


def test_daily_check_recomputes_overlay_breach_from_weight() -> None:
    payload = _benign_payload()
    portfolio = payload["portfolio_risk"]
    assert isinstance(portfolio, dict)
    portfolio["overlay_breach"] = False
    portfolio["layer_weights"] = {"overlay": 0.15}

    attention = {item.key for item in build_daily_check(payload).attention_items}

    assert "layer_budget" in attention


def test_daily_check_fails_closed_on_invalid_overlay_weight() -> None:
    payload = _benign_payload()
    portfolio = payload["portfolio_risk"]
    assert isinstance(portfolio, dict)
    portfolio["layer_weights"] = {"overlay": "not-a-number"}

    attention = {item.key for item in build_daily_check(payload).attention_items}

    assert "layer_budget" in attention


def test_daily_check_raises_on_all_attention_paths() -> None:
    check = build_daily_check(_stressed_payload())
    by_key = {item.key: item for item in check.items}
    assert by_key["data_freshness"].runbook_ref == "runbook §6.2"
    assert by_key["regime"].runbook_ref == "runbook §6.4"
    assert by_key["layer_budget"].runbook_ref == "runbook §6.3"
    assert by_key["p_metrics"].runbook_ref == "runbook §6.1"
    assert not check.all_clear


def test_daily_check_as_dict_is_json_safe() -> None:
    payload = build_daily_check().as_dict()
    dumped = json.loads(json.dumps(payload, ensure_ascii=False))
    assert dumped["all_clear"] is False
    assert len(dumped["items"]) == 5


def test_daily_check_rejects_unknown_runbook_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale runbook ref in a check must fail loudly (the anti-drift guard)."""

    import yquant.ops.daily_check as module

    real_build = module.build_runbook

    def _pruned_runbook() -> Any:
        runbook = real_build()
        return type(runbook)(
            sections=tuple(s for s in runbook.sections if s.ref != "runbook §6.4")
        )

    monkeypatch.setattr(module, "build_runbook", _pruned_runbook)
    with pytest.raises(ValueError, match="unknown runbook section"):
        build_daily_check()  # demo payload references §6.4 via the fired sentinel.


# ------------------------------------------------------------------- CLI ---


def test_ops_cli_daily_check_prints_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from yquant.cli import main

    assert main(["ops", "daily-check"]) == 0
    out = capsys.readouterr().out
    assert "ops daily-check" in out
    assert "need attention" in out
    assert "runbook §6.4" in out


def test_ops_cli_runbook_reports_no_gaps(capsys: pytest.CaptureFixture[str]) -> None:
    from yquant.cli import main

    assert main(["ops", "runbook"]) == 0
    out = capsys.readouterr().out
    assert "alert_binding_gaps: none" in out
    assert "runbook §6.2" in out


def test_ops_cli_interval_book_writes_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from yquant.cli import main

    out_path = tmp_path / "interval_book.json"
    assert main(["ops", "interval-book", "--output", str(out_path)]) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["version"] == "v1"
    assert len(payload["layers"]) == 4
    assert "interval_book_artifact" in capsys.readouterr().out


def test_ops_cli_daily_check_writes_artifact(tmp_path: Path) -> None:
    from yquant.cli import main

    out_path = tmp_path / "daily_check.json"
    assert main(["ops", "daily-check", "--output", str(out_path)]) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert "items" in payload and len(payload["items"]) == 5


def test_ops_cli_runbook_writes_artifact(tmp_path: Path) -> None:
    from yquant.cli import main

    out_path = tmp_path / "runbook.json"
    assert main(["ops", "runbook", "--output", str(out_path)]) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["alert_binding_gaps"] == []
    assert len(payload["runbook"]["sections"]) == 8


# ----------------------------------------------------------- fixtures ---


def _benign_payload() -> dict[str, Any]:
    return {
        "today_brief": {
            "as_of": "2025-01-02",
            "weather": {"state": "RiskOn", "composite": 1.0},
        },
        "opportunity_risk": {
            "thesis_sentinel": [
                {"us_ticker": "SMH", "verdict": "alive"},
            ],
        },
        "portfolio_risk": {
            "overlay_breach": False,
            "layer_weights": {"overlay": 0.05},
        },
        "system_health": {
            "data_freshness": {"daily_bars": "fresh"},
            "p_metrics": {"P1": "PASS", "P11": "PASS"},
        },
    }


def _stressed_payload() -> dict[str, Any]:
    return {
        "today_brief": {
            "as_of": "2025-01-02",
            "weather": {"state": "Crisis", "composite": -3.0},
        },
        "opportunity_risk": {
            "thesis_sentinel": [
                {"us_ticker": "SMH", "verdict": "alive"},
            ],
        },
        "portfolio_risk": {
            "overlay_breach": True,
            "layer_weights": {"overlay": 0.15},
        },
        "system_health": {
            "data_freshness": {"daily_bars": "stale (as of 2024-12-01)"},
            "p_metrics": {"P1": "PASS", "P11": "FAIL"},
        },
    }
