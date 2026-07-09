"""WP6 contract red-line acceptance harness (04 §4, P0-clear proof).

Each red-line check must (a) pass when the real enforcement code holds, and
(b) fail if the guard is bypassed — the negative cases below simulate the
"更方便的实现" the plan calls out as an instant P0, proving the harness would
catch it rather than rubber-stamp a green.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from yquant.qa import build_red_line_panel, run_red_line_checks
from yquant.qa.redlines import (
    RedLinePanel,
    RedLineResult,
    check_r1_overlay_cap,
    check_r2_leverage_three_conditions,
    check_r3_invalidation_required,
    check_r4_regime_veto,
    check_r5_llm_no_orders,
)


def test_all_five_red_lines_pass() -> None:
    results = run_red_line_checks()
    assert [r.code for r in results] == ["R1", "R2", "R3", "R4", "R5"]
    assert all(r.passed for r in results)


def test_r1_blocks_over_cap_and_admits_at_cap() -> None:
    r1 = check_r1_overlay_cap()
    assert r1.passed
    assert r1.detail["over_cap_blocked"] is True
    assert r1.detail["at_cap_admitted"] is True
    assert r1.detail["cap"] == 0.10


def test_r2_names_each_missing_condition() -> None:
    r2 = check_r2_leverage_three_conditions()
    assert r2.passed
    assert r2.detail["all_conditions_pass"] is True
    assert r2.detail["regime_block"] == ["regime_not_risk_on"]
    assert r2.detail["ma_block"] == ["below_10m_ma"]
    assert r2.detail["vix_block"] == ["vix_not_below_20"]


def test_r3_requires_machine_readable_invalidation() -> None:
    r3 = check_r3_invalidation_required()
    assert r3.passed
    assert r3.detail["blank_rejected"] is True
    assert r3.detail["vague_rejected"] is True
    assert r3.detail["concrete_admitted"] is True
    assert r3.detail["executor_blocks_blank"] is True


def test_r4_crisis_clears_and_gate_only_de_risks() -> None:
    r4 = check_r4_regime_veto()
    assert r4.passed
    assert r4.detail["crisis_overlay_weight"] == 0.0
    assert r4.detail["risk_off_overlay_weight"] == 0.04
    assert r4.detail["risk_on_overlay_weight"] == 0.08
    assert r4.detail["gate_only_de_risks"] is True


def test_r5_llm_has_no_order_surface() -> None:
    r5 = check_r5_llm_no_orders()
    assert r5.passed
    assert r5.detail["implements_signal_provider"] is True
    assert r5.detail["order_producing_methods"] == []
    assert r5.detail["emits_inferences_only"] is True
    assert r5.detail["explain_kind"] == "llm"


# --- negative cases: prove the harness catches a bypassed guard ---------------


def test_r1_negative_when_guardrail_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the overlay-cap guard stops flagging violations, R1 must go RED."""

    import yquant.qa.redlines as redlines

    monkeypatch.setattr(redlines, "validate_overlay_request", lambda **_: [])
    assert check_r1_overlay_cap().passed is False


def test_r3_negative_when_blank_invalidation_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a blank invalidation is treated as machine-readable, R3 must go RED."""

    import yquant.qa.redlines as redlines

    monkeypatch.setattr(redlines, "is_machine_readable_condition", lambda _: True)
    assert check_r3_invalidation_required().passed is False


def test_r4_negative_when_crisis_leaves_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the regime gate stops clearing Overlay on Crisis, R4 must go RED."""

    import yquant.qa.redlines as redlines

    def _passthrough(desired: object, regime: object, as_of: date) -> tuple[object, list]:
        return desired, []

    monkeypatch.setattr(redlines, "apply_regime_gate", _passthrough)
    assert check_r4_regime_veto().passed is False


# --- panel + serialisation ----------------------------------------------------


def test_panel_green_and_json_safe() -> None:
    panel = build_red_line_panel()
    assert isinstance(panel, RedLinePanel)
    assert panel.all_pass is True
    assert panel.failures == ()
    payload = panel.as_dict()
    assert payload["all_pass"] is True
    assert payload["total"] == 5
    assert payload["failed"] == []
    red_lines = payload["red_lines"]
    assert isinstance(red_lines, list)
    assert len(red_lines) == 5
    # round-trips through JSON without loss
    json.loads(json.dumps(payload))


def test_panel_render_text_reports_verdict() -> None:
    text = build_red_line_panel().render_text()
    assert "contract red-line panel" in text
    assert "verdict: GREEN" in text
    for code in ("R1", "R2", "R3", "R4", "R5"):
        assert f"[PASS] {code}" in text


def test_panel_render_text_flags_failure() -> None:
    failing = RedLinePanel(
        results=(
            RedLineResult(code="R1", name="cap", passed=False, detail={}),
        )
    )
    assert failing.all_pass is False
    assert failing.failures[0].code == "R1"
    text = failing.render_text()
    assert "[FAIL] R1" in text
    assert "verdict: RED (P0)" in text
    assert failing.as_dict()["failed"] == ["R1"]


# --- CLI ----------------------------------------------------------------------


def test_cli_redlines_prints_green_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from yquant.cli import main

    assert main(["qa", "redlines"]) == 0
    out = capsys.readouterr().out
    assert "verdict: GREEN" in out
    assert "R5 LLM 不产订单" in out


def test_cli_redlines_writes_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from yquant.cli import main

    out_path = tmp_path / "redlines.json"
    assert main(["qa", "redlines", "--output", str(out_path)]) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["all_pass"] is True
    assert len(payload["red_lines"]) == 5
    assert "red_line_panel_artifact" in capsys.readouterr().out
