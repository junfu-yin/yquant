"""Owner daily-check driver (08 §7 日检五分钟, WP11 exit gate).

The WP11 exit criterion is "委托人独立完成一次日检（录屏）": the owner, without
the builder, runs one deterministic day-check and reads a clear pass/fail list.
This module turns the six-page cockpit payload into exactly that — an ordered
list of checks, each ``ok``/attention with a one-line reason and, when it needs
action, the runbook section to open. It is pure and LLM-free so the check is
reproducible byte-for-byte (a recording of it is verifiable evidence).

Checks (in read order):
  1. 数据新鲜度      — the data-date banner is fresh (no stale series)
  2. 全球天气        — the committed regime; Crisis/RiskOff raises attention
  3. Thesis 哨兵     — any invalidated tactical thesis is a red item (S1 sell)
  4. 层预算          — Overlay ≤ 10% hard cap (P11)
  5. 系统健康        — P-metrics all PASS
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from yquant.ops.runbook import build_runbook
from yquant.ui.demo import build_demo_payload

_ATTENTION_REGIMES = {"Crisis", "RiskOff"}


@dataclass(frozen=True)
class CheckItem:
    """One line of the daily check."""

    key: str
    label: str
    ok: bool
    detail: str
    runbook_ref: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "ok": self.ok,
            "detail": self.detail,
            "runbook_ref": self.runbook_ref,
        }


@dataclass(frozen=True)
class DailyCheck:
    """The assembled day-check: an ordered checklist plus a single verdict."""

    as_of: str
    items: tuple[CheckItem, ...]

    @property
    def all_clear(self) -> bool:
        return all(item.ok for item in self.items)

    @property
    def attention_items(self) -> tuple[CheckItem, ...]:
        return tuple(item for item in self.items if not item.ok)

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "all_clear": self.all_clear,
            "items": [item.as_dict() for item in self.items],
        }


def build_daily_check(payload: dict[str, Any] | None = None) -> DailyCheck:
    """Assemble the owner's day-check from the six-page cockpit payload.

    ``payload`` defaults to the deterministic demo payload so the check runs
    end-to-end with no data repo; in production the scheduler hands in the live
    six-page payload. Runbook refs are validated against the real runbook so a
    stale reference cannot slip in.
    """

    data = build_demo_payload().to_dict() if payload is None else payload
    runbook = build_runbook()
    brief = data["today_brief"]
    opportunity = data["opportunity_risk"]
    portfolio = data["portfolio_risk"]
    health = data["system_health"]

    items: list[CheckItem] = []

    # 1. data freshness
    freshness = health.get("data_freshness", {})
    stale = sorted(k for k, v in freshness.items() if "stale" in str(v).lower())
    freshness_ok = bool(freshness) and not stale
    items.append(
        CheckItem(
            key="data_freshness",
            label="数据新鲜度",
            ok=freshness_ok,
            detail="所有序列新鲜" if freshness_ok else f"陈旧或缺失序列: {stale}",
            runbook_ref=None if freshness_ok else "runbook §6.2",
        )
    )

    # 2. global weather (regime)
    weather = brief["weather"]
    regime = weather["state"]
    regime_ok = regime not in _ATTENTION_REGIMES
    items.append(
        CheckItem(
            key="regime",
            label="全球天气",
            ok=regime_ok,
            detail=f"状态={regime} composite={weather['composite']}",
            runbook_ref=None if regime_ok else "runbook §6.4",
        )
    )

    # 3. Thesis sentinel red items
    fired = [
        row["us_ticker"]
        for row in opportunity["thesis_sentinel"]
        if row["verdict"] != "alive"
    ]
    items.append(
        CheckItem(
            key="thesis_sentinel",
            label="Thesis 哨兵",
            ok=not fired,
            detail="无失效命题" if not fired else f"失效命题(S1 卖出): {fired}",
            runbook_ref=None if not fired else "runbook §6.4",
        )
    )

    # 4. layer budget (Overlay hard cap)
    layer_weights = portfolio.get("layer_weights", {})
    try:
        overlay_weight = float(layer_weights.get("overlay", 0.0))
    except (TypeError, ValueError):
        overlay_weight = float("nan")
    overlay_breach = (
        not layer_weights
        or not math.isfinite(overlay_weight)
        or overlay_weight < 0
        or bool(portfolio.get("overlay_breach"))
        or overlay_weight > 0.10 + 1e-9
    )
    items.append(
        CheckItem(
            key="layer_budget",
            label="层预算",
            ok=not overlay_breach,
            detail=f"Overlay={overlay_weight:.2%} (硬上限 10%)",
            runbook_ref=None if not overlay_breach else "runbook §6.3",
        )
    )

    # 5. system health P-metrics
    p_metrics = health.get("p_metrics", {})
    failing = sorted(k for k, v in p_metrics.items() if str(v).upper() != "PASS")
    p_metrics_ok = bool(p_metrics) and not failing
    items.append(
        CheckItem(
            key="p_metrics",
            label="系统健康",
            ok=p_metrics_ok,
            detail="P 指标全绿" if p_metrics_ok else f"未通过或缺失: {failing}",
            runbook_ref=None if p_metrics_ok else "runbook §6.1",
        )
    )

    # Guard against a stale runbook reference sneaking in.
    known = runbook.refs()
    for item in items:
        if item.runbook_ref is not None and item.runbook_ref not in known:
            raise ValueError(f"daily-check references unknown runbook section {item.runbook_ref}")

    return DailyCheck(as_of=brief["as_of"], items=tuple(items))
