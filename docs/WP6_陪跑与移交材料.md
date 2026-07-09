# WP6 — 30 天陪跑与移交材料（04 §1 WP6 / §4 变更红线）

> 出口判据（04）：**P0/P1 清零 + 移交材料**。陪跑期"只修不加"。
> 本文是移交材料本体，配合可脚本化的红线验收台架，构成每日"P0 清零"的机器可校验证据。

## 1. 陪跑期的运行纪律

- **只修不加**：陪跑期只允许修复缺陷，不新增功能、不放宽任一红线。任何"更方便的实现"绕过五条红线之一即 P0（04 §4）。
- **每日重证**：每个交易日在收盘后运行红线验收台架（见 §3），要求 `verdict: GREEN`；任何 `RED (P0)` 即触发停机复盘，先修复再复跑。
- **每日日检**：委托人用 `ops daily-check`（WP11）做五分钟独立日检，覆盖数据新鲜度 / 政权 / Thesis 哨兵 / 分层预算 / P 指标。

## 2. 五条合同级红线（04 §4）与执行代码定位

| 红线 | 内容 | 执行代码（真实生产路径，非台架重实现） |
| --- | --- | --- |
| R1 | 战术层 10% 硬上限 | `discipline/overlay_guardrails.py` `validate_overlay_request`（`rule="overlay_cap"`） |
| R2 | 2x 条款三条件（RiskOn ∧ >10mMA ∧ VIX<20） | `overlay/leverage.py` `three_condition_gate` / `open_leverage_position` |
| R3 | 失效条件必填（机器可读） | `macro/schemas.py` `is_machine_readable_condition` + `overlay/leverage.py` 执行器 |
| R4 | 状态机否决权（Crisis 清空 Overlay，只降险） | `risk/regime_gate.py` `apply_regime_gate`（`_RETENTION`） |
| R5 | "LLM 不产订单" | `strategies/base.py` `SignalProvider` 协议 + `strategies/satellite/llm_providers.py`（ADR-22/24） |

## 3. 红线验收台架（每日 P0 清零证据）

台架代码：`yquant/qa/redlines.py`。它**驱动上表的真实执行代码**（不重实现），对每条红线各跑一个"合规"与一个"违规"用例，只有当守卫挡住违规、放行合规时该红线才判 `PASS`。

运行方式：

```bash
# 打印面板；GREEN 时退出码 0，RED (P0) 时退出码 1（可直接作为 CI/cron 门禁）
python -m yquant.cli qa redlines

# 同时落 JSON 证据（陪跑期逐日归档）
python -m yquant.cli qa redlines --output data/redlines/$(date +%F).json
```

面板输出（示例）：

```
contract red-line panel (04 §4):
  [PASS] R1 战术层 10% 硬上限
  [PASS] R2 2x 条款三条件
  [PASS] R3 失效条件必填
  [PASS] R4 状态机否决权
  [PASS] R5 LLM 不产订单
verdict: GREEN
```

**反向证据**：`tests/unit/test_redlines.py` 用 monkeypatch 模拟"绕过守卫"的实现（禁用 overlay-cap、放行空失效条件、Crisis 不清 Overlay），断言台架会翻红；`scripts/mutation_check.py` 另加 R1/R2/R4 三个变异体，证明一旦生产代码弱化红线，台架测试立即失败（10/10 mutants killed）。

## 4. 陪跑期每日运维命令清单

| 用途 | 命令 |
| --- | --- |
| 五条红线体检（门禁） | `python -m yquant.cli qa redlines` |
| 委托人五分钟日检 | `python -m yquant.cli ops daily-check` |
| 分层预注册区间书 | `python -m yquant.cli ops interval-book` |
| 机器可读运行手册 | `python -m yquant.cli ops runbook` |
| P 指标质量面板 | `python -m yquant.cli qa panel` |
| 四场景演习台账 | `python -m yquant.cli qa drills` |
| 账本回放（确定性 digest） | `python -m yquant.cli ledger replay` |
| 事件复盘 / 链完整性 | `python -m yquant.cli ledger incident` / `ledger chain` |
| 纸上机会簿影子对账 | `python -m yquant.cli paper` / `overlay paper` |
| 数据新鲜度 | `python -m yquant.cli data freshness ...` |

## 5. 陪跑结项检查单（P0/P1 清零）

- [ ] 陪跑期每日 `qa redlines` 均 GREEN（JSON 证据逐日归档于 `data/redlines/`）。
- [ ] 委托人独立完成每日 `ops daily-check`，无未处置 S1 告警。
- [ ] `qa panel` P 指标全绿；`ledger chain` 完整性校验通过。
- [ ] 全量 CI 绿：`ruff` / `mypy` / `pytest --cov-fail-under=90` / `mutation_check`。
- [ ] P0/P1 缺陷清零，且陪跑期未新增功能、未放宽任一红线。
