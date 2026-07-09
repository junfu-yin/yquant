"""Operational runbook (08 §7): the actionable index alerts bind to.

Every graded alert (:mod:`yquant.notify.graded`) carries a runbook reference so
an on-call owner has a *concrete* action, not just a red banner. Those
references (``runbook §6.1`` … ``§6.4``) were previously dangling strings; this
module makes them first-class, machine-readable sections and lets a test prove
that **every alert source resolves to a real section** (the "告警↔runbook 段落
对照" gate). It also carries the day/week/month ceremonies and the recovery
procedures the plan's runbook table-of-contents mandates.

Pure data + pure functions: no clock, no IO. The runbook is a frozen artefact
so its JSON digest is stable and can be diffed under review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yquant.notify.graded import FIXED_SOURCES


@dataclass(frozen=True)
class RunbookSection:
    """One actionable runbook entry: what fired, and the ordered steps to take."""

    ref: str  # e.g. "runbook §6.3" — matches the alert binding verbatim.
    title: str
    trigger: str
    severity_hint: str | None  # the severity that typically routes here.
    steps: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "title": self.title,
            "trigger": self.trigger,
            "severity_hint": self.severity_hint,
            "steps": list(self.steps),
        }


@dataclass(frozen=True)
class Runbook:
    """The whole runbook: alert-response sections plus the operating ceremonies."""

    sections: tuple[RunbookSection, ...]

    def refs(self) -> set[str]:
        return {section.ref for section in self.sections}

    def section(self, ref: str) -> RunbookSection | None:
        for section in self.sections:
            if section.ref == ref:
                return section
        return None

    def as_dict(self) -> dict[str, Any]:
        return {"sections": [section.as_dict() for section in self.sections]}


# The §6.x alert-response sections; the refs match graded.FIXED_SOURCES verbatim.
_ALERT_SECTIONS: tuple[RunbookSection, ...] = (
    RunbookSection(
        ref="runbook §6.1",
        title="通用告警处置（未分类源）",
        trigger="任意未在 FIXED_SOURCES 固定的告警（默认 S3 观察）",
        severity_hint="S3",
        steps=(
            "在 UI 设置与系统健康页确认告警上下文与 run_id",
            "`yquant ledger chain --event-id <id>` 回溯因果链",
            "若与决策相关则升级并按对应 §6.x 处置，否则记录观察即可",
        ),
    ),
    RunbookSection(
        ref="runbook §6.2",
        title="支柱缺失（P10 状态机支柱数据缺失）",
        trigger="pillar_missing：五支柱中有支柱因数据缺失被降级",
        severity_hint="S2",
        steps=(
            "`yquant data freshness` 定位缺失序列（VIX/HY OAS/NFCI 等）",
            "确认状态机是否已沿用上一有效读数（缺失沿用为设计行为）",
            "补数后 `yquant schedule run-once --job regime` 重算当日状态并入账",
        ),
    ),
    RunbookSection(
        ref="runbook §6.3",
        title="层预算越界（P11 Overlay/2x 硬上限）",
        trigger="layer_budget_breach：Overlay>10% 或 2x 名义越界",
        severity_hint="S1",
        steps=(
            "立即停止新增战术仓（红线：10% 为硬上限，只可下调）",
            "按 08 §6 防御序列：①Overlay 多头清至现金 ②2x 清零",
            "`yquant ledger replay --run-id <id> --strict` 复核越界当次决策",
            "记录事件并走变更流程（越界=正式变更，需四要素+重签区间书）",
        ),
    ),
    RunbookSection(
        ref="runbook §6.4",
        title="状态机切换（Crisis 进入升 S1）",
        trigger="regime_change / regime_change_crisis：政权状态迁移",
        severity_hint="S1",
        steps=(
            "确认新状态与触发支柱（regime 账本 regime_history）",
            "Crisis：执行强制清杠杆 overlay 并按收紧后波动目标缩仓",
            "RiskOff：Overlay 多头减半、2x 清零",
            "在交易台账登记状态驱动的调仓，全程留痕可回放",
        ),
    ),
)

# The operating ceremonies (08 §7 runbook table of contents).
_CEREMONY_SECTIONS: tuple[RunbookSection, ...] = (
    RunbookSection(
        ref="runbook §7.1",
        title="日检五分钟",
        trigger="每个交易日盘后",
        severity_hint=None,
        steps=(
            "`yquant ops daily-check` 或 UI 今日简报页",
            "看数据日期横幅、全球天气面板、Thesis 哨兵红项",
            "确认无 S1/S2 未处置告警、无越界；有则转对应 §6.x",
        ),
    ),
    RunbookSection(
        ref="runbook §7.2",
        title="周检",
        trigger="每周一次",
        severity_hint=None,
        steps=(
            "抽检回放一致性、执行质量（滑点回填）",
            "复核机会簿状态与三层预算水位",
            "LLM 抽检准确率与污染标记",
        ),
    ),
    RunbookSection(
        ref="runbook §7.3",
        title="月度仪式",
        trigger="每月一次",
        severity_hint=None,
        steps=(
            "混沌注入或消防演练择一（`python scripts/chaos_drill.py` / `yquant qa drills`）",
            "区间对照回顾：实盘滚动结果 vs 预注册区间书",
            "演习季：每季重跑一个历史场景保持肌肉记忆",
        ),
    ),
    RunbookSection(
        ref="runbook §8.1",
        title="恢复手册",
        trigger="数据勘误 / 模型回滚 / 备份还原",
        severity_hint=None,
        steps=(
            "数据勘误只可 append（manifest errata），不可原地改写",
            "模型/prompt 回滚走 provider 版本切换，ModelCard 留痕",
            "备份还原后 `yquant ledger replay --strict` 校验 digest 一致",
        ),
    ),
)


def build_runbook() -> Runbook:
    """Assemble the full operational runbook (alert-response + ceremonies)."""

    return Runbook(sections=(*_ALERT_SECTIONS, *_CEREMONY_SECTIONS))


def alert_binding_gaps(runbook: Runbook | None = None) -> list[str]:
    """Alert refs that do not resolve to a runbook section (should be empty).

    Closes the "每条 S1/S2 告警 → runbook 段落" loop: every source in
    :data:`~yquant.notify.graded.FIXED_SOURCES`, plus the ``§6.1`` default
    fallback, must land on a real section. A non-empty return is a defect.
    """

    book = runbook or build_runbook()
    known = book.refs()
    bound = {ref for _, ref in FIXED_SOURCES.values()}
    bound.add("runbook §6.1")  # the default-source fallback in AlertRouter._resolve.
    return sorted(ref for ref in bound if ref not in known)
