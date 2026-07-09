"""Contract red-line acceptance harness (04 §4, WP6 exit gate).

The plan names five *contract-level* red-lines; violating any one is a P0. WP6 is
a 30-day shadow-run whose exit is "P0/P1 清零 + 移交材料", so the run needs a
single, deterministic artefact that re-proves every red-line each day — the
machine-readable form of "P0 清零". This module drives the *real* enforcement
code (not a re-implementation) through both a compliant and a violating case for
each red-line and reports a pass only when the guard blocks the violation and
admits the compliant case.

The five red-lines (04 §4):
  R1 战术层 10% 硬上限   — the Overlay layer cannot exceed 10% (guardrails).
  R2 2x 条款三条件       — 2x opens only under RiskOn ∧ >10mMA ∧ VIX<20.
  R3 失效条件必填        — a machine-readable invalidation is mandatory.
  R4 状态机否决权        — Crisis force-clears Overlay; the gate only de-risks.
  R5 "LLM 不产订单"      — LLM providers emit scored inferences, never orders.

Pure and side-effect free, so a red-line run is itself replayable (07).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, cast

from yquant.discipline.overlay_guardrails import (
    OverlayExposure,
    OverlayGuardrailConfig,
    validate_overlay_request,
)
from yquant.macro.schemas import is_machine_readable_condition
from yquant.overlay.leverage import (
    LeverageOpenRequest,
    open_leverage_position,
    three_condition_gate,
)
from yquant.risk.regime_gate import apply_regime_gate
from yquant.risk.state_machine import RegimeState
from yquant.strategies.base import Inference, SignalProvider
from yquant.strategies.satellite.llm_providers import EarningsScoreProvider, LlmScore

if TYPE_CHECKING:
    from yquant.datasrc.protocols import DataRepo

_AS_OF = date(2025, 1, 2)


@dataclass(frozen=True)
class RedLineResult:
    """One red-line verdict: does the enforcement block the violation? (JSON-safe)."""

    code: str  # R1..R5
    name: str
    passed: bool
    detail: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "name": self.name,
            "passed": self.passed,
            "detail": dict(self.detail),
        }


def check_r1_overlay_cap() -> RedLineResult:
    """R1: an Overlay expression above 10% must be blocked, 10% admitted."""

    config = OverlayGuardrailConfig()
    over = validate_overlay_request(
        symbol="SMH",
        instrument_kind="ordinary",
        exposure=OverlayExposure(overlay_weight_after=0.11, symbol_weight_after=0.04),
        config=config,
    )
    at_cap = validate_overlay_request(
        symbol="SMH",
        instrument_kind="ordinary",
        exposure=OverlayExposure(overlay_weight_after=0.10, symbol_weight_after=0.04),
        config=config,
    )
    blocked = any(v.rule == "overlay_cap" for v in over)
    admitted = not at_cap
    return RedLineResult(
        code="R1",
        name="战术层 10% 硬上限",
        passed=blocked and admitted,
        detail={
            "cap": config.overlay_cap,
            "over_cap_blocked": blocked,
            "at_cap_admitted": admitted,
        },
    )


def check_r2_leverage_three_conditions() -> RedLineResult:
    """R2: 2x opens only when all three conditions hold; each drop is a named block."""

    all_hold = three_condition_gate(
        regime=RegimeState.RISK_ON, above_10m_ma=True, vix_level=15.0
    )
    not_risk_on = three_condition_gate(
        regime=RegimeState.NEUTRAL, above_10m_ma=True, vix_level=15.0
    )
    below_ma = three_condition_gate(
        regime=RegimeState.RISK_ON, above_10m_ma=False, vix_level=15.0
    )
    high_vix = three_condition_gate(
        regime=RegimeState.RISK_ON, above_10m_ma=True, vix_level=25.0
    )
    each_named = (
        not_risk_on == ["regime_not_risk_on"]
        and below_ma == ["below_10m_ma"]
        and high_vix == ["vix_not_below_20"]
    )
    return RedLineResult(
        code="R2",
        name="2x 条款三条件",
        passed=all_hold == [] and each_named,
        detail={
            "all_conditions_pass": all_hold == [],
            "regime_block": not_risk_on,
            "ma_block": below_ma,
            "vix_block": high_vix,
        },
    )


def check_r3_invalidation_required() -> RedLineResult:
    """R3: a blank / non-machine-readable invalidation must be refused."""

    blank_rejected = not is_machine_readable_condition("")
    vague_rejected = not is_machine_readable_condition("感觉不太行就走")
    concrete_ok = is_machine_readable_condition("SMH < 210")

    _, rejection = open_leverage_position(
        LeverageOpenRequest(
            ticker="SSO",
            weight=0.02,
            invalidation_condition="",  # blank — must be refused
            as_of=_AS_OF,
            above_10m_ma=True,
        ),
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
    )
    executor_blocks = (
        rejection is not None and rejection.rule == "invalidation_not_machine_readable"
    )
    return RedLineResult(
        code="R3",
        name="失效条件必填",
        passed=blank_rejected and vague_rejected and concrete_ok and executor_blocks,
        detail={
            "blank_rejected": blank_rejected,
            "vague_rejected": vague_rejected,
            "concrete_admitted": concrete_ok,
            "executor_blocks_blank": executor_blocks,
        },
    )


def check_r4_regime_veto() -> RedLineResult:
    """R4: Crisis clears Overlay to cash, RiskOff halves; the gate never adds."""

    from yquant.strategies.base import Layer, TargetPortfolio

    layers: dict[str, Layer] = {"SPY": "core", "SMH": "overlay"}
    desired = TargetPortfolio(
        as_of=_AS_OF,
        weights={"SPY": 0.5, "SMH": 0.08},
        layers=layers,
        cash_weight=0.42,
    )
    crisis, _ = apply_regime_gate(desired, RegimeState.CRISIS, _AS_OF)
    risk_off, _ = apply_regime_gate(desired, RegimeState.RISK_OFF, _AS_OF)
    risk_on, _ = apply_regime_gate(desired, RegimeState.RISK_ON, _AS_OF)

    crisis_clears = "SMH" not in crisis.weights and crisis.cash_weight > desired.cash_weight
    risk_off_halves = abs(risk_off.weights.get("SMH", 0.0) - 0.04) < 1e-9
    risk_on_untouched = risk_on.weights.get("SMH", 0.0) == 0.08
    never_adds = crisis.weights.get("SMH", 0.0) <= 0.08 and risk_off.weights["SMH"] <= 0.08
    return RedLineResult(
        code="R4",
        name="状态机否决权",
        passed=crisis_clears and risk_off_halves and risk_on_untouched and never_adds,
        detail={
            "crisis_overlay_weight": round(crisis.weights.get("SMH", 0.0), 6),
            "risk_off_overlay_weight": round(risk_off.weights.get("SMH", 0.0), 6),
            "risk_on_overlay_weight": round(risk_on.weights.get("SMH", 0.0), 6),
            "gate_only_de_risks": never_adds,
        },
    )


def _static_scorer(as_of: date, universe: list[str], repo: DataRepo) -> list[LlmScore]:
    return [LlmScore(symbol=sym, score=0.5, confidence=0.7, evidence=["demo"]) for sym in universe]


def check_r5_llm_no_orders() -> RedLineResult:
    """R5: an LLM provider emits scored inferences only — no order-producing surface."""

    provider = EarningsScoreProvider(_static_scorer, knowledge_cutoff=date(2024, 1, 1))
    # Structural: the SignalProvider contract has no order/trade/execute method.
    implements_contract = isinstance(provider, SignalProvider)
    order_surface = [
        attr
        for attr in ("place_order", "order", "execute", "trade", "submit")
        if hasattr(provider, attr)
    ]
    # Behavioural: predict returns Inference objects, never orders.
    outputs = provider.predict(_AS_OF, ["AAPL", "NVDA"], repo=cast("DataRepo", object()))
    all_inferences = outputs and all(isinstance(o, Inference) for o in outputs)
    llm_kind = all(o.explain.kind == "llm" for o in outputs)
    return RedLineResult(
        code="R5",
        name="LLM 不产订单",
        passed=bool(implements_contract and not order_surface and all_inferences and llm_kind),
        detail={
            "implements_signal_provider": implements_contract,
            "order_producing_methods": order_surface,
            "emits_inferences_only": bool(all_inferences),
            "explain_kind": "llm" if llm_kind else "mixed",
        },
    )


_CHECKS = (
    check_r1_overlay_cap,
    check_r2_leverage_three_conditions,
    check_r3_invalidation_required,
    check_r4_regime_veto,
    check_r5_llm_no_orders,
)


def run_red_line_checks() -> list[RedLineResult]:
    """Run all five contract red-line checks, ordered R1..R5."""

    return [check() for check in _CHECKS]


@dataclass(frozen=True)
class RedLinePanel:
    """A rollup of the five red-line verdicts with a single blocking verdict."""

    results: tuple[RedLineResult, ...]

    @property
    def all_pass(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> tuple[RedLineResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    def as_dict(self) -> dict[str, object]:
        return {
            "all_pass": self.all_pass,
            "total": len(self.results),
            "failed": [r.code for r in self.failures],
            "red_lines": [r.as_dict() for r in self.results],
        }

    def render_text(self) -> str:
        lines = ["contract red-line panel (04 §4):"]
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{mark}] {r.code} {r.name}")
        lines.append(f"verdict: {'GREEN' if self.all_pass else 'RED (P0)'}")
        return "\n".join(lines)


def build_red_line_panel() -> RedLinePanel:
    """Assemble the full contract red-line panel (the WP6 daily P0-clear proof)."""

    return RedLinePanel(results=tuple(run_red_line_checks()))
