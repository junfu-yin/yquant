# 03 · yquant 技术方案 v2（完整版）

> yquant 项目文档包 · 编号 03 · **本文档是项目的唯一权威规格（Single Source of Truth）**
> 版本：v2.0 · 日期：2026-07-05 · 取代：《量化交易-AI系统_技术方案.md》（下称 v1）
> 读者：项目委托人、外包开发者。外包方开工前必须通读本文档与《04 SOW》；对本文档的任何疑问，先查 §12 FAQ，再走 04 篇约定的答疑流程。
> 配套文档：01（竞品调研，回答"为什么是这个定位"）、02（思想实验，回答"每个决策的推理"）、04（SOW，回答"怎么干活怎么验收"）。

---

## 1. 一页纸摘要

**yquant 是什么**：面向 A 股个人投资者的本地部署系统，三个支柱——①可信的数据与回测基座（内置 A 股真实交易约束与回测陷阱测试）；②AI 投研简报引擎（LLM 每日自动读完自选股全部公告/新闻/异动，输出可溯源的结构化简报）；③决策纪律引擎（规则化建议 → 人工确认 → 交易留痕 → AI 复盘归因）。

**yquant 不是什么**：不是预测涨跌的模型，不是自动下单机器人，不是又一个量化研究框架。LLM 在本系统中**永远不直接产生买卖信号**。

**为什么这样定位**：GitHub 上 6 万星的 ai-hedge-fund 与 5.6 万星的 TradingAgents 均自我声明"仅教育研究用途"；个人相对机构在预测与速度上无优势，真实稀缺的是信息带宽、纪律和验证工具（推理全文见 02 篇）。

**成功标准**（90 天检验）：使用者每周打开 ≥4 天；每日投研时间 ≤10 分钟且自选股重大事件零遗漏；所有交易 100% 留痕并复盘；回测陷阱测试集持续全绿。

## 2. 目标、指标与范围

### 2.1 用户画像（唯一目标用户）

A 股个人投资者一名：自有资金人工下单（券商 App），自选股 10~30 只，可接受周/月频调仓，日常可投入盯盘时间 <30 分钟，具备基本 Python 使用能力（能跑 `pip install` 与 `streamlit run`），持有可用的 LLM API（OpenAI 兼容协议，默认 DeepSeek）。

### 2.2 用户故事（验收的最终依据）

- US-1 每个交易日 17:30，我打开"今日简报"页，5 分钟内看完：自选股今天所有公告/新闻的分级摘要（每条附原文链接）、行情异动、"今日必看 Top3"、组合风险状态。
- US-2 我想验证"红利低波月度轮动"是否靠谱，在"回测实验室"选策略与区间，得到含真实成本、样本外划分、与沪深 300 对照的报告，以及"该结论可信度"的自检结果。
- US-3 策略触发调仓建议时，系统生成建议单（含仓位与理由）；我逐项过完 checklist 才能标记"已执行"，执行记录自动入交易日志。
- US-4 每周一早上，我收到 AI 复盘周报：上周操作与计划的偏离、当前组合暴露、连续亏损/回撤告警。
- US-5 任何时候数据拉取失败，系统降级运行并在界面明确提示数据日期，绝不静默使用过期数据。

### 2.3 可度量成功指标

| 维度 | 指标 | 目标值 | 测量方式 |
|---|---|---|---|
| 有用性 | 周活跃天数 | ≥4 天/周（连续 4 周） | app 打开日志 |
| 信息带宽 | 自选股重大事件（severity≥4）遗漏率 | 0 | 每周人工抽查对照巨潮公告 |
| 时间效率 | 每日投研耗时 | ≤10 分钟 | 使用者自报 |
| 纪律 | 交易留痕率 / 计划外交易占比 | 100% / 呈下降趋势 | 交易日志统计 |
| 可信度 | 回测陷阱测试集 | 持续全绿 | CI 自动运行 |
| 成本 | LLM 日均费用 | ≤¥2 | tokens 记账表 |

### 2.4 非目标（v1.0 明确不做，写入合同）

高频/日内策略；tick 或分钟级数据；自动下单与券商接口；期货期权港美股（美股仅指数行情可选展示）；社交舆情爬虫（雪球/股吧，反爬成本高且信噪比低）；多用户/SaaS 化；策略参数自动寻优服务；LLM 直接输出买卖建议。任何新需求先进 `docs/icebox.md`，仅在里程碑评审讨论。

### 2.5 与 v1 方案的差异对照

| 项 | v1 | v2 | 理由（详见 02 篇） |
|---|---|---|---|
| 终局 | Phase 3 AI 自主执行 | 移出范围（icebox） | 尾部风险不对称 + 合规收紧（ADR-02） |
| LLM 用法 | 情绪打分→因子→信号 | 事件结构化简报，禁产信号 | 时效链路上对 T+1 个人无效；历史新闻无法可靠回测（ADR-03/04） |
| 回测 | 直接跑 backtrader | 先建 A 股约束层+陷阱测试集 | 免费数据+默认框架必然产出虚假曲线（ADR-05） |
| 数据 | AkShare 单源直连 | 适配器+落盘+多备源 | 上游接口失效是常态（ADR-06） |
| 范围 | 数据/舆情/大类资产/实盘全铺 | 三支柱收窄 | 反 Qbot 式大而全（02 实验 6 死法四） |
| 保留 | AkShare、backtrader、Streamlit、人机协作、复盘 | 保留并深化 | v1 的这些判断正确 |

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  调度层  APScheduler（交易日 16:30 数据更新 → 17:00 简报生成   │
│          → 17:30 通知推送；周一 08:00 复盘周报）                │
└──────┬──────────────────────────────────────────────────────┘
       │
┌──────▼──────────┐   ┌──────────────────┐   ┌────────────────┐
│ M1 数据基座      │──▶│ M2 回测引擎       │──▶│ M3 策略库       │
│ 多源适配器        │   │ backtrader +     │   │ S1 均线择时     │
│ 本地落盘(Parquet │   │ A股约束层 +      │   │ S2 红利低波     │
│ +SQLite)         │   │ 成本模型 +       │   │ S3 动量轮动     │
│ 质检器           │   │ 陷阱测试集       │   │ (walk-forward) │
└──────┬──────────┘   └──────────────────┘   └───────┬────────┘
       │                                             │信号(非指令)
┌──────▼──────────┐                          ┌───────▼────────┐
│ M4 AI简报引擎    │                          │ M5 决策纪律引擎 │
│ 公告/新闻/异动   │─────── 事件卡片 ────────▶│ 建议单+checklist│
│ →LLM结构化→校验  │                          │ 交易日志+风控   │
│ (可溯源/可评测)  │                          │ AI复盘周报      │
└──────┬──────────┘                          └───────┬────────┘
       │                                             │
┌──────▼─────────────────────────────────────────────▼────────┐
│ M6 界面与通知  Streamlit 5 页 + 飞书 Bot 摘要推送              │
└─────────────────────────────────────────────────────────────┘
```

**数据流向单向依赖**：M1→(M2,M4)；M3 依赖 M2；M5 消费 M3 信号与 M4 事件卡；M6 只读各模块产物。禁止反向依赖与跨层直连（例如 M6 不得直接调 AkShare）。

## 4. 技术选型与复用/自研边界

| 层 | 选型 | 复用/自研 | 说明 |
|---|---|---|---|
| 语言/环境 | Python 3.11+，Poetry 管理依赖 | — | 单机部署，Linux/macOS/WSL |
| 行情数据 | AkShare（主）、Tushare Pro / BaoStock（备） | 复用 | 全部经 M1 适配器与落盘层，业务代码禁止直连 |
| 存储 | Parquet（行情列存）+ SQLite（业务表）+ DuckDB（分析查询） | 复用 | 单机零运维；表结构见 §7 |
| 回测 | backtrader | 复用+自研 | **自研 A 股约束层与陷阱测试集**（本项目核心差异点之一） |
| LLM | OpenAI 兼容 API；默认 DeepSeek，可切换 Qwen/GLM/Claude | 复用 | 统一 `llm_client` 封装：重试、超时、tokens 记账、prompt 版本化 |
| 界面 | Streamlit | 复用 | 不追求前端美观，追求信息密度 |
| 通知 | 飞书自定义机器人 webhook | 复用 | 仅推送摘要+链接，正文在本地 |
| 调度 | APScheduler（进程内） | 复用 | 交易日历感知（非交易日跳过） |
| 测试 | pytest + 回测陷阱测试集 + LLM 标注评测集 | 自研 | 验收的核心载体 |

**自研仅限四点**：A 股约束层、陷阱测试集、AI 简报引擎（含校验与评测）、纪律引擎。其余一律复用。

## 5. 模块详细规格

> 约定：所有接口给出 Python 签名与 docstring 级说明；`AS-x` 表示"待外包在 M0 阶段实测确认的假设"，确认结果写入 `docs/assumptions.md`。

### 5.1 M1 数据基座

**职责**：把外部不可靠的数据接口，转化为本地可靠、可追溯、经质检的数据资产。

**数据范围（v1.0）**：
1. 证券主档：全 A 股票列表（含已退市），代码/名称/上市日/退市日/所属板块/行业（申万一级）。
2. 日线行情：全 A 2016-01-01 至今，OHLCV+成交额+换手率，前后复权因子。
3. 交易日历：2016 至今+未来一年。
4. 指数日线：沪深300、中证500、中证红利、创业板指。
5. 公司公告：自选股范围，标题+链接+发布时间+（可得时）正文；候选接口 `ak.stock_notice_report` 等（AS-1：外包实测确认最优接口与字段）。
6. 财经新闻：自选股相关，东财/新浪接口（AS-2）。
7. 财务摘要：营收/净利/ROE/资产负债率/股息率，**必须带公告日期 announce_date**（AS-3：确认哪个接口提供公告日；若无，用报告期+法定披露截止日保守推算并在数据中标记 `announce_date_estimated=True`）。
8. 龙虎榜、北向资金（可选，接口可用即接）。

**核心接口**：

```python
class DataSource(Protocol):
    """所有数据源适配器的统一协议。新增备源只需实现本协议。"""
    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    def fetch_stock_list(self, include_delisted: bool = True) -> pd.DataFrame: ...
    def fetch_announcements(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    # 其余同理，完整清单见 data/protocols.py

class DataRepo:
    """唯一的数据读取入口。业务模块只允许 import 本类。"""
    def get_bars(self, symbols: list[str], start: date, end: date,
                 adjust: Literal["none","qfq","hfq"] = "hfq") -> pd.DataFrame:
        """返回列: symbol,date,open,high,low,close,volume,amount,turnover,
        adj_factor,is_suspended,limit_up_price,limit_down_price
        保证: 按交易日历对齐; 停牌日 is_suspended=True 且价格前向填充并标记;
        涨跌停价按板块规则(主板±10%/创业科创±20%/ST±5%/北交所±30%)预计算。"""
    def get_universe(self, on_date: date) -> list[str]:
        """返回该历史日期当时上市存续的全部股票（含此后退市者）——幸存者偏差防护的关键。"""

def update_all(watchlist: list[str]) -> QualityReport:
    """每日增量更新入口（调度层调用）。任何单接口失败: 重试3次→切备源→
    仍失败则跳过并记入 QualityReport, 绝不中断整体、绝不写入部分脏数据。"""
```

**质检器（每日更新后强制运行）**：K 线覆盖率对照交易日历（缺失即报）、价格异常跳变检测（|Δclose|>21% 且非除权除息日→报警）、复权因子连续性、公告时间戳非未来。产出 `QualityReport` 存表并在 UI 显示最近数据日期。

**验收标准**：全 A 2016 至今日线入库，质检通过率 ≥99%；universe 含退市股 ≥300 只（AS-4：以实际接口可得数量为准，下限 100）；断网/接口失败场景下 `update_all` 行为符合上述降级规范（用 mock 测试证明）；任一备源可通过配置一键切换。

### 5.2 M2 回测引擎（backtrader + A 股约束层）

**职责**：让回测数字可信。哲学：回测是测谎仪，不是寻宝图（ADR-05）。

**A 股约束层（自研，`backtest/china_broker.py`，继承 `bt.brokers.BackBroker`）**：
1. **T+1**：当日买入股份 `available_for_sell=False`，次一交易日解锁。
2. **涨跌停撮合**：目标日 `open==limit_up_price`（一字涨停）→ 买单拒绝成交；`open==limit_down_price` → 卖单拒绝；非一字触板日按可配置规则（默认：以 min(委托价, 收盘价) 成交，保守化处理）。拒单事件计入报告"未成交统计"。
3. **停牌**：`is_suspended=True` 日禁止任何成交；持仓停牌股按最后价估值并在报告标注。
4. **成本模型**（全部可配置，默认值）：佣金 0.025% 双边、最低 5 元/笔；印花税 0.05% 仅卖出；过户费 0.001% 双边；滑点 0.1%（按成交价比例）。**以上默认值外包不得修改，用户可在 config 覆盖。**
5. **最小交易单位**：100 股整数倍；现金不足自动缩量。

**统一回测入口**：

```python
@dataclass
class BacktestConfig:
    strategy_cls: type; strategy_params: dict
    universe: list[str] | Literal["all_a"]  # "all_a"=逐日动态universe(防幸存者偏差)
    start: date; end: date
    cash: float = 300_000
    cost_multiplier: float = 1.0   # 报告自动跑 0/1/2 三档
    rebalance: Literal["daily","weekly","monthly"] = "monthly"

def run_backtest(cfg: BacktestConfig) -> BacktestReport: ...

@dataclass
class BacktestReport:
    equity_curve: pd.Series; benchmark_curve: pd.Series   # 沪深300对照,强制
    metrics: dict  # 年化收益/波动/最大回撤/夏普/卡玛/胜率/换手率/成本占收益比
    cost_sensitivity: dict[float, dict]                   # {0:…,1:…,2:…}
    rejected_orders: pd.DataFrame                          # 涨跌停/停牌拒单明细
    warnings: list[str]  # 如"universe为静态列表,存在幸存者偏差风险"
    def to_html(self) -> str: ...                          # 单文件报告
```

**Walk-forward 评估器**：`walk_forward(cfg, train_years=4, test_years=1)` —— 滚动划分（如 2016-19 训练/2020 测试、2017-20/2021……），仅样本外拼接曲线进入最终结论；输出参数敏感性热力图（参数 ±20% 网格下的指标变化）。

**验收标准**：§8 陷阱测试集 T1–T6 全绿；同配置重复运行结果逐字节一致（确定性）；全 A universe 十年月频回测单次运行 ≤10 分钟（性能达不到时允许预计算缓存，但需文档说明）。

### 5.3 M3 基准策略库

**职责**：提供三个"够用且诚实"的低频规则策略作为系统的默认武器与回测引擎的验证载体。**不追求跑赢一切，追求结论诚实。**

| 编号 | 策略 | 规则要点（完整规则见 `strategies/specs/*.md`，外包按 spec 实现） | 频率 |
|---|---|---|---|
| S1 | 沪深300双均线择时 | 指数收盘价 20 日均线上穿 120 日均线→满仓 300ETF；下穿→空仓货币。仅作趋势过滤基准 | 周检查 |
| S2 | 红利低波轮动 | 股息率前 100 → 剔除 ST/停牌/上市<1年 → 按 120 日波动率升序取 20 只等权 | 月调仓 |
| S3 | 行业动量轮动 | 申万一级行业指数 12-1 月动量前 3，对应 ETF 等权持有 | 月调仓 |
| B0 | 买入持有沪深300 | 唯一强制对照基准 | — |

每个策略交付物 = 代码 + spec 文档 + walk-forward 报告 + **一段诚实的结论文字**（包括"该策略在 20XX-20XX 样本外未跑赢 B0"这类负面结论，负面结论不扣验收分——见 04 SOW）。

### 5.4 M4 AI 投研简报引擎（本项目的灵魂模块）

**职责**：每个交易日收盘后，把自选股发生的一切压缩成 5 分钟可读完、可溯源、可分级的结构化简报。**输入是文本与行情，输出是事件卡片，绝不是买卖建议。**

**流水线**：
```
采集(M1: 公告/新闻/行情) → 预过滤(去重/黑名单词/长度) → LLM结构化(逐条)
→ 硬校验(schema/数字回验/链接存在) → 分级汇总(Top3/红旗) → 入库 → 推送
```

**事件卡片 Schema（LLM 输出必须严格符合，pydantic 校验）**：

```python
class EventCard(BaseModel):
    symbol: str
    source_type: Literal["announcement","news","price_action","financial"]
    event_type: Literal["业绩相关","回购增持","减持","股权质押","重大合同",
        "监管处分","诉讼仲裁","资产重组","分红送转","人事变动","异动提示","其他"]
    severity: int = Field(ge=1, le=5)      # 5=当天必须知道
    direction: Literal["利多","利空","中性","不确定"]
    one_line: str = Field(max_length=60)   # 一句话摘要
    key_numbers: list[str]                 # 从原文抽取的关键数字,逐个回验
    rationale: str = Field(max_length=200) # 为什么这样分级/定向
    source_url: str                        # 必填,校验非空
    prompt_version: str
```

**幻觉防护（硬性规则，代码强制）**：
- `key_numbers` 中每个数字必须能在原文文本中正则匹配到，匹配不到→整卡降级为"仅标题转发"并打 `unverified` 标。
- LLM 对不确定内容必须输出 `direction="不确定"`，prompt 中明示"宁可不确定，不可编造"。
- 每张卡片 UI 上一键跳原文。

**分级与推送规则**：severity≥4 → 进入"今日必看"并飞书推送；减持/质押/监管处分/诉讼 四类 direction=利空 时额外标红旗；同一 symbol 当日 >8 条时仅保留 severity 前 5。

**成本与降级**：`config.llm.daily_budget_cny`（默认 2 元）。预算耗尽→剩余条目"仅标题+来源分类"降级处理并在简报头部声明。全部 LLM 调用记账入 `llm_usage` 表。

**Prompt 管理**：prompt 存 `prompts/*.md` 带版本号；修改 prompt = 提版本号 + 在评测集上回归（见验收）。

**验收标准**：交付 60 条人工标注评测集（外包整理素材、委托人终审标注；覆盖 12 类 event_type、正负样本均衡）上：event_type 准确率 ≥85%，severity ±1 容忍准确率 ≥85%，direction 准确率 ≥80%，**编造数字检出后漏杀率 = 0**（即所有含未回验数字的卡片必须被降级）；连续 5 个交易日全自动稳定产出；单日 30 只自选股全流程 ≤15 分钟、成本 ≤¥2。

### 5.5 M5 决策纪律引擎

**职责**：把"知道"变成"做到"。对抗行为偏差是本模块唯一使命。

**建议单**：策略调仓信号触发时生成：

```python
class TradeProposal(BaseModel):
    id: str; created_at: datetime
    strategy: str; symbol: str; side: Literal["buy","sell"]
    target_weight: float          # 目标仓位
    suggested_shares: int         # 按最新价与仓位规则折算,100股整数倍
    position_rule: str            # 如"单票≤15%,组合股票仓位≤90%"
    reason: str                   # 引用策略规则条文,非LLM生成
    related_events: list[str]     # 关联的EventCard id
    status: Literal["pending","confirmed","modified","rejected","expired"]
```

**执行前 checklist（UI 强制逐项勾选后才可标记"已执行"）**：①本操作是否由既定策略规则触发（若否，必须填写"计划外理由"，该字段进入周复盘重点）；②是否处于冷静期；③执行后单票权重是否 ≤ 上限（默认 15%，config 可改）；④组合当前回撤状态是否允许加仓（回撤 >10% 时默认禁止加仓，仅提示可覆盖）；⑤已阅读该股票今日红旗事件（若有）。

**风控规则引擎（纯规则，无 LLM）**：单票上限、行业上限（默认 35%）、组合最大回撤告警线 10%/强提醒线 15%、连续 3 笔亏损平仓→自动进入 3 个交易日冷静期（软约束：期间新建仓需在 checklist 额外确认）。所有触发记入 `risk_events` 表。

**交易日志**：确认执行的 proposal 转为 `trade_log` 记录（成交价、股数、费用由用户回填实际值）；持仓与净值每日快照。

**AI 复盘周报（LLM 的第二个用武之地）**：输入 = 本周 trade_log + proposals + risk_events + 组合表现；输出 = ①计划 vs 实际偏离清单；②计划外交易及其理由的模式归纳；③风控触发回顾；④下周关注事项。同样带 prompt 版本与原始数据引用，**不得给出新的买卖建议**。

**验收标准**：checklist 未完成时"已执行"按钮不可点（UI 测试）；风控规则 10 个场景单元测试全过；周报在含 ≥5 笔交易的模拟数据上生成且引用数据可核对。

### 5.6 M6 界面与通知

Streamlit 多页应用，五页：

1. **今日简报**：数据日期与质检状态横幅｜今日必看 Top3｜红旗区｜按自选股分组的事件卡流｜行情异动表。
2. **组合与风控**：持仓/权重/浮盈亏、净值曲线 vs 沪深300、回撤水位、风控事件流。
3. **回测实验室**：策略下拉+参数表单+区间选择 → 运行 → 内嵌 BacktestReport（含成本三档与 warnings 显著展示）。
4. **交易台账**：pending proposals（含 checklist 交互）、历史日志、周复盘归档。
5. **设置**：自选股管理、LLM 配置与用量仪表、数据源切换、风控参数、飞书 webhook。

飞书推送两条固定消息：交易日 17:30 简报摘要（Top3 标题+红旗数+链接）、周一 08:00 周报摘要。推送失败仅记日志不重试轰炸。

**验收标准**：冷启动到简报页首屏 ≤5 秒（数据已就绪前提下）；所有页面在数据缺失日显示明确的降级提示而非报错栈。

### 5.7 M7 调度与运维

APScheduler 进程常驻（`yquant daemon` 命令）：交易日 16:30 `update_all` → 成功后 17:00 简报流水线 → 17:30 推送；周一 08:00 周报。交易日历判断用本地日历表。所有任务写 `job_runs` 表（开始/结束/状态/错误摘要），UI 设置页可见最近 20 次。日志用 loguru，按天轮转，保留 30 天。

## 6. 目录结构与工程规范

```
yquant/
├── pyproject.toml            # Poetry;锁定依赖版本
├── config.example.toml       # 全部可配置项与注释;真实config不入库
├── prompts/                  # 版本化prompt: brief_v1.md, review_v1.md
├── yquant/
│   ├── data/                 # M1: sources/(akshare_,tushare_,baostock_), repo.py, quality.py
│   ├── backtest/             # M2: china_broker.py, runner.py, walk_forward.py, report.py
│   ├── strategies/           # M3: base.py, s1_ma_timing.py, s2_dividend_lowvol.py, s3_momentum.py, specs/
│   ├── brief/                # M4: pipeline.py, schemas.py, verifier.py, llm_client.py
│   ├── discipline/           # M5: proposals.py, checklist.py, risk_rules.py, journal.py, review.py
│   ├── ui/                   # M6: app.py, pages/
│   └── scheduler/            # M7: daemon.py, calendar.py
├── tests/
│   ├── traps/                # §8 陷阱测试集(T1-T6)
│   ├── eval/                 # M4 标注评测集与评测脚本
│   └── unit/
├── data/                     # 运行时产物(gitignore): parquet/, yquant.db, logs/
└── docs/                     # 本文档包 + assumptions.md + icebox.md + ADR追加
```

**规范**：ruff + mypy(基础级) 过 CI；公共接口全类型注解；每模块 README 说明职责与禁区；提交规范 Conventional Commits；分支 `feat/wpX-*`，PR 必须关联 SOW 工作包编号且附验收自测证据（详见 04）。**禁止事项**：业务代码直连数据源、LLM 输出未经 schema 校验入库、静默 except、硬编码密钥（一律走环境变量/config）。

## 7. 存储设计

**Parquet（列存，DuckDB 查询）**：`data/parquet/daily_bars/`（分区：year）、`index_bars/`、`financials/`。

**SQLite 业务表（DDL 摘要，完整 DDL 交付时给出）**：

```sql
stocks(symbol PK, name, board, industry_sw1, list_date, delist_date, status);
trade_calendar(date PK, is_open);
announcements(id PK, symbol, title, url, pub_time, raw_text, fetched_at);
event_cards(id PK, symbol, date, source_type, event_type, severity, direction,
            one_line, key_numbers_json, rationale, source_url, unverified,
            prompt_version, created_at);
proposals(id PK, ...同5.5..., checklist_json, decided_at);
trade_log(id PK, proposal_id FK, symbol, side, shares, price, fees, exec_time, note);
portfolio_snapshots(date PK, positions_json, cash, nav);
risk_events(id PK, date, rule, detail_json);
llm_usage(id PK, ts, task, model, prompt_version, tokens_in, tokens_out, cost_cny);
job_runs(id PK, job, started_at, ended_at, status, error);
quality_reports(date PK, summary_json);
```

## 8. 回测陷阱测试集（验收核心，`tests/traps/`）

每条测试都是"给系统下毒，验证它能吐出来"。**全绿是 M2 及之后一切策略结论的前置条件。**

| 编号 | 陷阱 | 测试方法 | 通过判据 |
|---|---|---|---|
| T1 前视偏差 | 构造用"公告日前财务数据"选股的策略 | 框架的特征可见性检查（数据行带 announce_date，回测日<announce_date 时该行不可见） | 该策略取到的财务值全为 NaN/旧值；直接访问未来列抛异常 |
| T2 幸存者偏差 | 同一策略分别跑静态现存股票池 vs 动态 `get_universe()` | 两次回测收益差被完整报告；静态池运行时 `warnings` 必含幸存者偏差警告 | 警告存在且动态池含 ≥N 只退市股参与过持仓 |
| T3 涨跌停 | 构造某日一字涨停的合成数据+当日买入信号 | 检查成交记录 | 零成交，拒单入 rejected_orders |
| T4 成本敏感 | 高换手策略（周频满换） | 报告三档成本 | 2x 档收益显著低于 0 档，且报告自动生成三档对比 |
| T5 复权 | 含大比例送转股的真实样例（如历史上 10 送 10 案例） | 除权日前后持仓市值连续性 | 净值曲线无跳变（误差<0.1%） |
| T6 停牌 | 停牌期内发出的买卖信号 | 成交记录 | 停牌日零成交；复牌首日按规则处理 |

外加确定性测试（同 seed 同结果）与 T0 冒烟（B0 基准年化 ≈ 指数实际年化，误差主要来自费用）。

## 9. 里程碑计划（单人外包，兼职口径约 6–9 周）

| 里程碑 | 内容 | 预估人日 | 出口判据（Gate） |
|---|---|---|---|
| M0 环境与假设验证 | 仓库/CI/依赖；AS-1~4 接口实测报告 | 3–4 | assumptions.md 全部落定；三数据源冒烟通过 |
| M1 数据基座 | §5.1 全部 | 6–8 | 质检 ≥99%；退市股入库；断源降级测试过 |
| M2 回测引擎 | §5.2 + §8 | 6–8 | **陷阱测试集全绿** |
| M3 策略库 | §5.3 三策略 + walk-forward 报告 | 5–7 | 报告交付且结论诚实（含 K1 判定材料） |
| M4 简报引擎 | §5.4 | 7–9 | 评测集达标；5 日稳定运行；成本达标 |
| M5 纪律引擎+UI+调度 | §5.5–5.7 | 8–10 | 用户故事 US-1~5 逐条演示通过 |
| M6 陪跑期 | 30 天真实使用，仅修缺陷不加功能 | 机动 | §2.3 指标达标评审 |

**项目级 kill/pivot 判据（提前写死，防沉没成本绑架）**：
- **K1**（M3 后评审）：若 S1–S3 样本外全部同时"收益低于 B0 且最大回撤大于 B0"→ 停止自研策略投入，策略层收缩为"指数择时提示 + 手动组合跟踪"，资源全部转向 M4/M5。
- **K2**（M4 中）：评测集经两轮 prompt 迭代仍 <70% → 简报降级为"聚合+规则分类"形态，去 LLM 判读。
- **K3**（M6 中）：连续两周使用 <2 次 → 冻结开发，产品形态复盘，而非继续堆功能。

## 10. 运行环境与成本预算

单机部署（家用电脑常开或 2C4G 轻量云主机，约 ¥50–80/月）；LLM 按 §2.3 预算 ≤¥2/日（DeepSeek 档位实测富余，AS-5 外包在 M4 给出实测账单）；Tushare Pro 积分按需（预算 ≤¥500/年，若 AkShare 足够则省略）；无其他付费依赖。

## 11. 风险与合规

- **合规**：系统仅供使用者本人研究与决策辅助，不对外提供投资建议或荐股信号（避免触及投顾监管）；v1.0 不接任何自动下单接口（ADR-09）；若未来评估半自动执行，须另行专项合规评估（icebox）。
- **免责声明**：UI 底部与 README 固定声明"历史回测不代表未来收益，本系统不构成投资建议"。
- **数据风险**：上游接口失效（→多备源+落盘）、字段口径变更（→质检器拦截）。
- **密钥安全**：LLM key、Tushare token、飞书 webhook 全部环境变量注入，仓库含 `.env.example`。
- **技术债红线**：任何"临时绕过陷阱测试"的代码合入均视为验收不通过。

## 12. FAQ（外包开工前必读，预答高频疑问）

**Q1 为什么不用 Qlib？** 我们不做因子研究平台。Qlib 的能力半径与本项目三支柱几乎不重叠，引入只会增加复杂度。见 01 篇 §2.1。
**Q2 为什么 LLM 不直接给买卖建议？这不是 AI 交易系统吗？** 这是本项目最重要的设计决策（ADR-03），完整推理见 02 篇实验 1/3。实现时若发现某处"顺手让 LLM 建议一下"很方便——请不要，这属于 §6 禁止事项。
**Q3 backtrader 停止维护了，要不要换 vectorbt？** 不换。我们是低频策略，backtrader 的成熟度与事件级撮合表达力更匹配；速度瓶颈用预计算缓存解决。若实现中遇到无法逾越的框架缺陷，走变更流程（04 §5）。
**Q4 AkShare 某接口挂了/字段变了怎么办？** 这正是适配器模式存在的原因：修对应 adapter 或切备源，业务层零改动。接口频繁失效本身请记入 assumptions.md 供选型复审。
**Q5 历史公告拿不到全量正文怎么办？** 允许"标题+链接"降级模式，EventCard 打 `unverified`；正文可得性以 M0 实测为准（AS-1）。
**Q6 评测集 60 条谁标注？** 外包收集素材并预标，委托人终审。争议条目以委托人判定为准。
**Q7 策略跑不赢沪深300，算我做得不好吗？** 不算。验收看的是流程正确与结论诚实（§5.3），负面结论同样是合格交付物，K1 判据正是为此准备的。
**Q8 可以引入 LangChain/LangGraph 吗？** 不建议。M4 是单步结构化任务，裸调 API + pydantic 足够，减少依赖面。若坚持引入需在 PR 中论证收益。
**Q9 时间与时区？** 全系统 Asia/Shanghai，存储 ISO8601 带时区。
**Q10 交付形式？** 见 04 SOW §4：代码仓库 + 全绿 CI + 部署文档（从零到跑通 ≤30 分钟）+ 每里程碑验收演示。

---

*变更管理：对本文档的任何修改需在文末追加变更记录并同步 02 篇 ADR。*

| 版本 | 日期 | 变更 |
|---|---|---|
| v2.0 | 2026-07-05 | 基于 v1 全面重构定位与规格，首次发布 |
