# 03 · yquant 技术方案 v2（完整版）

> yquant 项目文档包 · 编号 03 · **本文档是项目的唯一权威规格（Single Source of Truth）**
> 版本：v2.0 · 日期：2026-07-05 · 取代：《量化交易-AI系统_技术方案.md》（下称 v1）
> 读者：项目委托人、外包开发者。外包方开工前必须通读本文档与《04 SOW》；对本文档的任何疑问，先查 §12 FAQ，再走 04 篇约定的答疑流程。
> 配套文档：01（竞品调研，回答"为什么是这个定位"）、02（思想实验，回答"每个决策的推理"）、04（SOW，回答"怎么干活怎么验收"）。

---

## 1. 一页纸摘要

**yquant 是什么**：面向**美股（主）与港股（辅）**个人投资者的本地部署系统，三个支柱——①可信的数据与回测基座（内置美股/港股真实交易约束与回测陷阱测试）；②AI 投研简报引擎（LLM 每日自动读完自选股全部公告/新闻/异动，输出可溯源的结构化简报）；③决策纪律引擎（规则化建议 → 人工确认 → 交易留痕 → AI 复盘归因）。

**yquant 不是什么**：不是预测涨跌的模型，不是自动下单机器人，不是又一个量化研究框架。LLM 在本系统中**永远不直接产生买卖信号**。

**为什么这样定位**：GitHub 上 6 万星的 ai-hedge-fund 与 5.6 万星的 TradingAgents 均自我声明"仅教育研究用途"；个人相对机构在预测与速度上无优势，真实稀缺的是信息带宽、纪律和验证工具（推理全文见 02 篇）。

**成功标准**（90 天检验）：使用者每周打开 ≥4 天；每日投研时间 ≤10 分钟且自选股重大事件零遗漏；所有交易 100% 留痕并复盘；回测陷阱测试集持续全绿。

## 2. 目标、指标与范围

### 2.1 用户画像（唯一目标用户）

美股/港股个人投资者一名：自有资金人工下单（券商 App，如富途/老虎/IBKR），自选股 10~30 只（以美股为主、港股为辅），可接受周/月频调仓，日常可投入盯盘时间 <30 分钟，具备基本 Python 使用能力（能跑 `pip install` 与 `streamlit run`），持有可用的 LLM API（OpenAI 兼容协议，默认 DeepSeek）。

### 2.2 用户故事（验收的最终依据）

- US-1 每天早晨（美股隔夜收盘后，约北京时间 08:00），我打开"今日简报"页，5 分钟内看完：自选股隔夜（美股）与昨日（港股）所有公告/新闻的分级摘要（每条附原文链接）、行情异动、"今日必看 Top3"、组合风险状态。
- US-2 我想验证"标普红利月度轮动"是否靠谱，在"回测实验室"选策略与区间，得到含真实成本、样本外划分、与标普500（美股）/恒生指数（港股）对照的报告，以及"该结论可信度"的自检结果。
- US-3 策略触发调仓建议时，系统生成建议单（含仓位与理由）；我逐项过完 checklist 才能标记"已执行"，执行记录自动入交易日志。
- US-4 每周一早上，我收到 AI 复盘周报：上周操作与计划的偏离、当前组合暴露、连续亏损/回撤告警。
- US-5 任何时候数据拉取失败，系统降级运行并在界面明确提示数据日期，绝不静默使用过期数据。

### 2.3 可度量成功指标

| 维度 | 指标 | 目标值 | 测量方式 |
|---|---|---|---|
| 有用性 | 周活跃天数 | ≥4 天/周（连续 4 周） | app 打开日志 |
| 信息带宽 | 自选股重大事件（severity≥4）遗漏率 | 0 | 每周人工抽查对照 SEC EDGAR（美股）/ 披露易 HKEXnews（港股） |
| 时间效率 | 每日投研耗时 | ≤10 分钟 | 使用者自报 |
| 纪律 | 交易留痕率 / 计划外交易占比 | 100% / 呈下降趋势 | 交易日志统计 |
| 可信度 | 回测陷阱测试集 | 持续全绿 | CI 自动运行 |
| 成本 | LLM 日均费用 | ≤¥2 | tokens 记账表 |

### 2.4 非目标（v1.0 明确不做，写入合同）

高频/日内策略；tick 或分钟级数据；自动下单与券商接口；期货期权；A 股与其他市场（本项目仅覆盖美股与港股，A 股不在范围；美股为主、港股为辅）；社交舆情爬虫（Reddit/StockTwits/雪球，反爬成本高且信噪比低）；多用户/SaaS 化；策略参数自动寻优服务；LLM 直接输出买卖建议。任何新需求先进 `docs/icebox.md`，仅在里程碑评审讨论。

### 2.5 与 v1 方案的差异对照

| 项 | v1 | v2 | 理由（详见 02 篇） |
|---|---|---|---|
| 终局 | Phase 3 AI 自主执行 | 移出范围（icebox） | 尾部风险不对称 + 合规收紧（ADR-02） |
| LLM 用法 | 情绪打分→因子→信号 | 事件结构化简报，禁产信号 | 新闻情绪时效链路上对个人无效；历史新闻无法可靠回测（ADR-03/04） |
| 回测 | 直接跑 backtrader | 先建美股/港股约束层+陷阱测试集 | 免费数据+默认框架必然产出虚假曲线（ADR-05） |
| 数据 | AkShare 单源直连 | 适配器+落盘+多备源（yfinance/AkShare/EDGAR/HKEXnews） | 上游接口失效是常态（ADR-06） |
| 范围 | 数据/舆情/大类资产/实盘全铺 | 三支柱收窄 | 反 Qbot 式大而全（02 实验 6 死法四） |
| 保留 | AkShare、backtrader、Streamlit、人机协作、复盘 | 保留并深化（数据源切换为 yfinance/AkShare/EDGAR/HKEXnews） | v1 的这些判断正确 |

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  调度层  APScheduler（按各市场收盘锚定，时点均为北京时间：       │
│          港股：收盘 16:00 后 → 16:30 数据更新 → 17:00 港股简报； │
│          美股：隔夜收盘后 → 06:00 数据更新 → 07:30 隔夜简报 →    │
│          08:00 推送合并视图；盘后公告（EDGAR 8-K）补采后增量推送 │
│          红旗；周一 09:00 复盘周报。夏令时切换自动跟随交易所日历）│
└──────┬──────────────────────────────────────────────────────┘
       │
┌──────▼──────────┐   ┌──────────────────┐   ┌────────────────┐
│ M1 数据基座      │──▶│ M2 回测引擎       │──▶│ M3 策略库       │
│ 多源适配器        │   │ backtrader +     │   │ S1 均线择时     │
│ 本地落盘(Parquet │   │ 美股/港股约束层 +│   │ S2 红利低波     │
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

**数据流向单向依赖**：M1→(M2,M4)；M3 依赖 M2；M5 消费 M3 信号与 M4 事件卡；M6 只读各模块产物。禁止反向依赖与跨层直连（例如 M6 不得直接调 yfinance/EDGAR）。

## 4. 技术选型与复用/自研边界

| 层 | 选型 | 复用/自研 | 说明 |
|---|---|---|---|
| 语言/环境 | Python 3.11+，Poetry 管理依赖 | — | 单机部署，Linux/macOS/WSL |
| 行情数据 | yfinance（主，美股/港股）、AkShare（备，美股/港股）、Stooq（备） | 复用 | 全部经 M1 适配器与落盘层，业务代码禁止直连 |
| 公告数据 | 美股：SEC EDGAR（`efts.sec.gov` 全文检索 + `data.sec.gov` 提交）；港股：披露易 HKEXnews | 复用 | 官方一手来源，免费；经 M1 适配器落盘 |
| 存储 | Parquet（行情列存）+ SQLite（业务表）+ DuckDB（分析查询） | 复用 | 单机零运维；表结构见 §7 |
| 回测 | backtrader | 复用+自研 | **自研美股/港股约束层与陷阱测试集**（本项目核心差异点之一） |
| LLM | OpenAI 兼容 API；默认 DeepSeek，可切换 Qwen/GLM/Claude | 复用 | 统一 `llm_client` 封装：重试、超时、tokens 记账、prompt 版本化 |
| 界面 | Streamlit | 复用 | 不追求前端美观，追求信息密度 |
| 通知 | 飞书自定义机器人 webhook | 复用 | 仅推送摘要+链接，正文在本地 |
| 调度 | APScheduler（进程内） | 复用 | 交易日历感知（非交易日跳过；美股/港股各一份日历，含夏令时） |
| 测试 | pytest + 回测陷阱测试集 + LLM 标注评测集 | 自研 | 验收的核心载体 |

**自研仅限四点**：美股/港股约束层、陷阱测试集、AI 简报引擎（含校验与评测）、纪律引擎。其余一律复用。

**细化复用清单（"能抄现成就别自己写"，为承接方省决策成本）**：

| 需求 | 直接复用 | 禁止自研的原因 |
|---|---|---|
| 交易日历 | 美股用 `pandas_market_calendars`（NYSE/NASDAQ，含夏令时与半日市）、港股用其 HKEX 日历落盘 | 自己推算节假日/夏令时必错 |
| 复权（split/dividend adjust） | yfinance `auto_adjust`/`actions` 直接取拆股与分红，或落盘调整因子 | 手推调整因子易在拆股/特别股息上出错 |
| 美股/港股 broker（T+0/交收/停牌/撮合） | 基于 backtrader `BackBroker` 改造（本项目自研点，但站在框架实现上） | 从零写事件级撮合成本高 |
| 停牌/LULD/VCM 规则 | 规则已在 §5.1/§5.2 给出，直接实现纯函数 | 已给数据，无需再调研 |
| 回测指标（夏普/回撤/卡玛等） | `quantstats` 或 `empyrical` 计算 | 指标口径易算错 |
| LLM 调用 | OpenAI 官方 SDK（兼容协议）+ 自写薄封装 `llm_client`（重试/超时/记账） | 不引入 LangChain（见 FAQ Q8） |
| 结构化输出校验 | `pydantic` v2 | — |
| 数字/金额归一化 | 自写容差比对，处理千分位、`M/B/K`（million/billion/thousand）、百分号等英文量纲 | 自己写解析易漏 case |
| Streamlit 多页 | Streamlit 原生 `pages/` 多页机制 | — |
| 调度 | APScheduler `BackgroundScheduler` + 交易日历守卫 | — |
| 飞书推送 | 飞书自定义机器人 webhook，requests 直发 | — |
| 列存查询 | DuckDB 直接查 Parquet | 不自建查询层 |

## 5. 模块详细规格

> 约定：所有接口给出 Python 签名与 docstring 级说明；`AS-x` 表示"待外包在 M0 阶段实测确认的假设"，确认结果写入 `docs/assumptions.md`。

### 5.1 M1 数据基座

**职责**：把外部不可靠的数据接口，转化为本地可靠、可追溯、经质检的数据资产。

**市场范围**：美股（主，NYSE/NASDAQ/AMEX）与港股（辅，HKEX 主板）。两个市场各自维护独立的交易日历、交收制度与微观结构规则；A 股不在范围。

**数据范围（v1.0）**：
1. 证券主档：美股 + 港股股票列表（含已退市/已摘牌），代码/名称/上市日/退市日/所属交易所/行业（GICS 板块与行业组）。美股代码用 ticker（如 `AAPL`），港股代码用 5 位数字带交易所后缀（如 `0700.HK`）。
2. 日线行情：美股 2010-01-01 至今、港股 2010-01-01 至今，OHLCV+成交额，**拆股/分红调整因子**（split/dividend adjust factor）。
3. 交易日历：2010 至今+未来一年，**含美股夏令时切换、半日市（如感恩节次日、圣诞前夜）与港股台风/黑雨临时休市**。
4. 指数日线：标普500（^GSPC）、纳斯达克100（^NDX）、恒生指数（^HSI）、恒生科技指数（^HSTECH）。
5. 公司公告：自选股范围，标题+链接+发布时间+（可得时）正文。美股走 SEC EDGAR（8-K/10-Q/10-K/S-1/Form 4 等），港股走披露易 HKEXnews（业绩/须予公布交易/配售/回购等）（AS-1：外包实测确认最优接口与字段）。
6. 财经新闻：自选股相关，Yahoo Finance / 公司 IR / 主流财经站点接口（AS-2）。
7. 财务摘要：营收/净利/EPS/ROE/资产负债率/股息率，**必须带公告日期 announce_date**（美股取 EDGAR 提交日 `filed`；港股取 HKEXnews 发布日）（AS-3：确认接口是否提供公告日；若无，用报告期+法定披露截止日保守推算并在数据中标记 `announce_date_estimated=True`）。
8. 内部人交易（美股 Form 4）、做空比例/short interest（可选，接口可用即接）。

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
                 adjust: Literal["none","adjusted"] = "adjusted") -> pd.DataFrame:
        """返回列: symbol,market,date,open,high,low,close,volume,amount,
        adj_factor,is_halted,halt_reason,session
        保证: 按对应市场交易日历对齐; 停牌/停牌恢复日 is_halted=True 并标记原因;
        adjust="adjusted" 时按拆股+分红调整因子回溯调整价格(默认),
        adjust="none" 时返回原始成交价。美股/港股均无每日涨跌停价字段
        (改由 §5.2 约束层按 LULD/VCM/停牌规则在撮合时处理)。"""
    def get_universe(self, on_date: date, market: Literal["us","hk","all"] = "all") -> list[str]:
        """返回该历史日期当时上市存续的全部股票（含此后退市/摘牌者）——幸存者偏差防护的关键。"""

def update_all(watchlist: list[str]) -> QualityReport:
    """每日增量更新入口（调度层调用）。任何单接口失败: 重试3次→切备源→
    仍失败则跳过并记入 QualityReport, 绝不中断整体、绝不写入部分脏数据。"""
```

**交易机制与微观结构规则（硬性说明，M1 落盘时标记，M2 撮合时使用）**：
美股与港股**均无 A 股式的每日涨跌停价**，但各有需要落盘/预计算的约束事实。实现纯函数 `market_rules(symbol, market, date) -> MarketRuleSet`，返回当日适用的交收周期、可否日内交易、以及需要在撮合层拒单/暂停的条件（AS-6：外包在 M0 核对以下规则与生效时点，落定至 `assumptions.md`；有冲突以交易所规则为准）：

| 市场 | 交收 | 日内交易 | 熔断 / 波动控制 | 收盘机制 |
|---|---|---|---|---|
| 美股（NYSE/NASDAQ） | **T+1**（2024-05-28 起，此前 T+2） | 允许（受 PDT 规则约束：账户 <$25k 时 5 个交易日内 day trade ≤3 次） | **个股 LULD**（Limit Up-Limit Down，触发 5 分钟限价带暂停）；**市场级熔断** Level 1/2/3（标普500 日内跌 7%/13%/20%） | 收盘竞价（closing auction）产生官方收盘价 |
| 港股（HKEX 主板） | **T+2** | 允许 | **VCM 市场波动调节机制**（成分股偏离参考价 ±10% 触发 5 分钟冷静期，每节交易时段限一次）；无市场级百分比熔断 | **收市竞价时段（CAS）**，价格限于参考价 ±5% |

落盘字段：每根 K 线带 `session`（regular/half_day）、`is_halted`、`halt_reason`（如 `luld_pause`/`vcm_cooldown`/`company_suspension`/`typhoon`）。因美股/港股无静态涨跌停价，价格异常检测改由质检器用"拆股/分红调整后收益跳变 + 公司行动日历"判定（见下）。

**质检器（每日更新后强制运行）**：K 线覆盖率对照对应市场交易日历（缺失即报，含夏令时/半日市/临时休市正确处理）、**价格异常跳变检测**（阈值按调整后日收益动态设定：`|调整后 log-return|` 超过该股 250 日波动的 N 倍 且 非拆股/分红/已知停牌复牌日 → 报警，而非固定百分比）、拆股/分红调整因子连续性、公告时间戳非未来（按公告所在市场时区判断）。产出 `QualityReport` 存表并在 UI 显示最近数据日期与各市场最近交易日。

**验收标准**：美股 + 港股 2010 至今日线+调整因子入库，质检通过率 ≥99%；`get_universe` 含退市/摘牌股 ≥300 只（AS-4：以实际接口可得数量为准，下限 100）；断网/接口失败场景下 `update_all` 行为符合上述降级规范（用 mock 测试证明）；任一备源可通过配置一键切换。

### 5.2 M2 回测引擎（backtrader + 美股/港股约束层）

**职责**：让回测数字可信。哲学：回测是测谎仪，不是寻宝图（ADR-05）。

**美股/港股约束层（自研，`backtest/broker_us.py` + `backtest/broker_hk.py`，均继承 `bt.brokers.BackBroker`；共享基类 `MarketBroker`）**：
1. **交收锁定（非 A 股 T+1 禁卖，而是资金/份额交收）**：美股/港股均允许**日内买卖**（无 A 股式当日买入不可卖），约束改为**交收周期占用可用资金/可交割份额**——美股 **T+1 交收**（2024-05-28 起，此前 T+2）、港股 **T+2 交收**。**实现要点（难点，预先点明）**：backtrader 默认现金即时可用，须自建"交收批次账本"——买入卖出后按 `settle_date=trade_date + N` 记账，未交收资金/份额在其到账日之前不计入可用额度（回测中现金充裕时影响小，但为与 PaperBroker 共享同一约束、避免上线后漂移，回测层必须实现）。美股账户 `<$25k` 时叠加 **PDT 规则**（5 个滚动交易日内 day trade ≤3 次，超限拒新开日内单并入 `rejected_orders`；`account_equity` 达标则关闭该限制）。
2. **微观结构撮合（取代 A 股涨跌停撮合）**：美股/港股均**无每日涨跌停价**，撮合按 M1 落盘的 `is_halted/halt_reason/session` 与市场规则处理：
   - **停牌/停市**：`is_halted=True` 日（`company_suspension`/`typhoon`/`black_rain` 等）→ 任何成交拒绝，持仓按最后有效价估值并在报告标注。
   - **美股 LULD / 市场级熔断**：日内触发 LULD 限价带暂停或市场级熔断（Level 1/2/3）当日，成交价约束在当日 `[low, high]` 内；若目标撮合价越过熔断触发边界，按保守价（买取 `max`、卖取 `min` 的可成交价）成交，越界不可成交部分入 `rejected_orders`。
   - **港股 VCM / 收市竞价（CAS）**：VCM 冷静期日成交价须落在当日 `[low, high]`；以收盘价为撮合基准的策略（月频调仓多在收盘执行）用 CAS 官方收盘价，价格自然受 ±5% 参考价约束。
   - 日频回测的默认撮合基准价为**收盘价（收盘竞价/CAS 官方收盘价）**，并强制校验成交价 ∈ 当日 `[low, high]`；违反即拒单入账。
   - 所有拒单事件计入报告"未成交统计"（`rejected_orders`）。
3. **成本模型（全部可配置，默认值；美股/港股分别计费）**：
   - **美股**：无印花税；佣金按券商（默认零佣金，如富途/老虎/IBKR 阶梯）；**SEC 交易费**（卖出，费率随监管调整，默认按最新公告值，M0 核对）+ **FINRA TAF**（卖出，按股数，默认最新值）；滑点 0.05%（大盘股，按成交价比例）。
   - **港股**：**印花税 0.1% 双边**（买卖各收，向上取整至港元）；**交易征费/交易费/结算费**（SFC 交易征费、联交所交易费、CCASS 结算费，默认最新费率）；佣金按券商（默认最低收费档）；滑点 0.1%。
   - **以上默认费率外包不得随意修改，须在 `assumptions.md` 记录取值日期与出处（AS-6）；用户可在 config 覆盖。**
4. **最小交易单位**：**美股** 1 股（默认；支持券商碎股则可设 `allow_fractional=True`）；**港股**按每手股数（`lot_size`，各股不同，从 M1 证券主档取，如 0700.HK 每手 100 股），现金不足自动按手缩量。

**统一回测入口**：

```python
@dataclass
class BacktestConfig:
    strategy_cls: type; strategy_params: dict
    # "all_us"/"all_hk"/"all"=逐日动态universe(防幸存者偏差)
    universe: list[str] | Literal["all_us","all_hk","all"]
    market: Literal["us","hk","mixed"] = "us"  # 决定交收/费用/日历规则
    start: date; end: date
    cash: float = 100_000          # 币种由 market 决定(us=USD, hk=HKD)
    cost_multiplier: float = 1.0   # 报告自动跑 0/1/2 三档
    rebalance: Literal["daily","weekly","monthly"] = "monthly"

def run_backtest(cfg: BacktestConfig) -> BacktestReport: ...

@dataclass
class BacktestReport:
    equity_curve: pd.Series; benchmark_curve: pd.Series   # 标普500/恒生对照,强制
    metrics: dict  # 年化收益/波动/最大回撤/夏普/卡玛/胜率/换手率/成本占收益比
    cost_sensitivity: dict[float, dict]                   # {0:…,1:…,2:…}
    rejected_orders: pd.DataFrame                          # 停牌/熔断/PDT拒单明细
    warnings: list[str]  # 如"universe为静态列表,存在幸存者偏差风险"
    def to_html(self) -> str: ...                          # 单文件报告
```

**Walk-forward 评估器**：`walk_forward(cfg, train_years=4, test_years=1)` —— 滚动划分（如 2016-19 训练/2020 测试、2017-20/2021……），仅样本外拼接曲线进入最终结论；输出参数敏感性热力图（参数 ±20% 网格下的指标变化）。

**验收标准**：§8 陷阱测试集 T1–T6 全绿；同配置重复运行结果逐字节一致（确定性）；全美股 universe（约 6000 只在市 + 退市，逐日动态）十年月频回测单次运行 ≤10 分钟（港股 universe 更小，同样达标）。

> **性能实现路径（预先给方向，避免在优化上无止境烧 token）**：backtrader 事件驱动 + 全美股（约 6000 只）× 10 年日线，纯事件循环大概率达不到 10 分钟。**推荐分层**：①信号计算与选股（均线、动量、波动率排序等）在 backtrader **之外**用 pandas/numpy **向量化预计算**，产出每个调仓日的目标持仓列表；②backtrader 只负责按目标持仓做撮合、约束（交收/停牌/熔断/费用）与净值核算，不在 Strategy 内做重指标计算；③预计算结果按 `(universe_hash, 参数, 区间)` 落盘缓存，walk-forward 各窗口复用。若采用缓存，需在模块 README 说明缓存键与失效条件。此路径为建议，允许承接方提出等效替代方案（走变更流程）。

### 5.3 M3 基准策略库

**职责**：提供三个"够用且诚实"的低频规则策略作为系统的默认武器与回测引擎的验证载体。**不追求跑赢一切，追求结论诚实。**

| 编号 | 策略 | 规则要点（完整规则见 `strategies/specs/*.md`，外包按 spec 实现） | 频率 |
|---|---|---|---|
| S1 | 标普500双均线择时 | 指数收盘价 50 日均线上穿 200 日均线→满仓 SPY；下穿→空仓货币基金/短债 ETF。仅作趋势过滤基准 | 周检查 |
| S2 | 红利低波轮动 | 股息率前 100（标普/纳斯达克成分为主） → 剔除停牌/上市<1年/流动性不足 → 按 120 日波动率升序取 20 只等权 | 月调仓 |
| S3 | GICS 板块动量轮动 | GICS 11 大板块 ETF（如 XLK/XLF/XLE…）12-1 月动量前 3，等权持有 | 月调仓 |
| B0 | 买入持有标普500（SPY） | 唯一强制对照基准（港股策略以恒生指数 ETF 2800.HK 为对照） | — |

每个策略交付物 = 代码 + spec 文档 + walk-forward 报告 + **一段诚实的结论文字**（包括"该策略在 20XX-20XX 样本外未跑赢 B0"这类负面结论，负面结论不扣验收分——见 04 SOW）。

### 5.4 M4 AI 投研简报引擎（本项目的灵魂模块）

**职责**：每个交易日收盘后，把自选股发生的一切压缩成 5 分钟可读完、可溯源、可分级的结构化简报。**输入是文本与行情，输出是事件卡片，绝不是买卖建议。**

**简报覆盖窗口（重要，与"零遗漏"指标直接相关）**：美股与港股收盘时间不同（均以北京时间计），且美股大量重要公告（8-K、财报）常在**美东盘后**披露，需按市场分班次覆盖：
- **港股盘后简报（北京时间 17:00）**：覆盖窗口 = 上一交易日港股收盘至当日港股收盘（16:00）后采集到的内容，含 HKEXnews 当日披露；头部标注"港股截至 16:00 收盘"。
- **美股隔夜补采（北京时间 06:00）**：美股隔夜收盘（美东 16:00 ≈ 北京 04:00–05:00，含夏令时）后拉取当日行情与 SEC EDGAR 盘后 8-K/Form 4 等；对新增公告增量结构化，产生 severity≥4/红旗事件则在 **07:30 隔夜简报**中标出。
- 次日 **08:00 生成"隔夜合并视图"**（美股隔夜 + 港股上一交易日），保证 §2.3 的**重大事件（severity≥4）零遗漏以"美股 06:00 补采 + 08:00 合并 / 港股 17:00 班次"为口径**，而非仅以单一班次为准。
- （此窗口划分为默认建议，委托人可在评审时调整时点；调整只改调度配置，不改流水线代码。夏令时切换由交易所日历自动驱动，班次锚定"市场收盘后 N 小时"而非固定墙钟。）

**流水线**：
```
采集(M1: 公告/新闻/行情) → 预过滤(去重/黑名单词/长度) → 输入裁剪(要素段抽取+截断)
→ LLM结构化(逐条) → 硬校验(schema/数字回验/链接存在) → 分级汇总(Top3/红旗) → 入库 → 推送
```

**输入裁剪策略（硬性，直接决定 token 与 ¥2/日 预算能否守住）**：单份公告/文件正文可达数万至十几万英文词（10-K 年报、S-1 招股书、重组文件），逐条整篇喂 LLM 会击穿 token 预算与"单日 ≤15 分钟"约束。规定：
1. **优先规则抽取要素段**：对结构化程度高的文件（10-Q/10-K 财报、8-K 条目、港股业绩公告），先用正则/关键段落定位（如 8-K 的 Item 编号、"Net income""Revenue""guidance"、港股"股东应占溢利""每股盈利"附近 ±N 字）抽取要素段，只把要素段 + 标题喂 LLM。
2. **兜底截断**：无法定位要素段时，对正文做 `MAX_INPUT_CHARS`（默认 8000 字符，config 可调）**左截断保留首尾**（首部含核心结论、尾部含关键财务数据/签署），并在卡片标记 `input_truncated=True`。
3. **分类前置**：能用标题 + source_type 规则直接判定的低价值类目（如"Notice of Annual General Meeting"、纯行政类 6-K）走规则分类，**不进 LLM**，直接省 token。
4. 单份输入 token 上限与当日累计预算双重熔断，触发即走 §"成本与降级"。

**事件卡片 Schema（LLM 输出必须严格符合，pydantic 校验）**：

```python
class EventCard(BaseModel):
    symbol: str
    market: Literal["us","hk"]
    source_type: Literal["announcement","news","price_action","financial"]
    event_type: Literal["业绩财报","指引调整","回购增持","内部人交易","并购重组",
        "重大合同","监管调查","诉讼仲裁","股权融资/增发","分红拆股","人事变动",
        "异动提示","其他"]
    severity: int = Field(ge=1, le=5)      # 5=当天必须知道
    direction: Literal["利多","利空","中性","不确定"]
    one_line: str = Field(max_length=60)   # 一句话摘要
    key_numbers: list[str]                 # 从原文抽取的关键数字,逐个归一化后回验
    rationale: str = Field(max_length=200) # 为什么这样分级/定向
    source_url: str                        # 必填,校验非空(EDGAR/HKEXnews原文链接)
    input_truncated: bool = False          # 输入是否被裁剪/截断(见输入裁剪策略)
    prompt_version: str
```

**幻觉防护（硬性规则，代码强制）**：
- **数字回验采用"归一化后比对"，非朴素正则**（这是本模块核心攻坚点，值得投入）：原文数字形态多样（`1,000万` / `$1.2B` / `1,200 million` / `10,000,000` / `10.00%` / `(1,234)` 括号负数）。回验流程 = ①把 `key_numbers` 与原文候选数字都归一化到统一量纲（去千分位、英文量纲 `K/M/B/thousand/million/billion` 折算、百分号处理、括号负数、货币符号剥离），②在容差内（默认相对误差 1e-6）比对。**只有归一化后仍无法在原文找到匹配的数字，才判定为编造**。目标：编造数字漏杀率 = 0 的同时，避免把正确卡片大量误杀为 `unverified`（后者会拖垮分类/方向准确率）。
- 命中编造：整卡降级为"仅标题转发"并打 `unverified` 标；`input_truncated=True` 的卡片若数字回验失败，优先归因于截断而非编造，标 `unverified` 但保留 LLM 分类结果供人工复核。
- LLM 对不确定内容必须输出 `direction="不确定"`，prompt 中明示"宁可不确定，不可编造"。
- 每张卡片 UI 上一键跳原文。

**分级与推送规则**：severity≥4 → 进入"今日必看"并飞书推送；并购重组/监管调查/诉讼仲裁/内部人大额减持 四类 direction=利空 时额外标红旗；同一 symbol 当日 >8 条时仅保留 severity 前 5。

**成本与降级**：`config.llm.daily_budget_cny`（默认 2 元）。预算耗尽→剩余条目"仅标题+来源分类"降级处理并在简报头部声明。全部 LLM 调用记账入 `llm_usage` 表。

**Prompt 管理**：prompt 存 `prompts/*.md` 带版本号；修改 prompt = 提版本号 + 在评测集上回归（见验收）。

**验收标准**：交付评测集（外包整理素材、委托人终审标注；覆盖 13 类 event_type、正负样本均衡），**样本量 ≥120 条（每类 ≥8 条，严重事件类目——并购重组/监管调查/诉讼仲裁/内部人交易——每类 ≥12 条）**，以降低小样本统计噪声。指标：
- event_type 准确率 ≥85%；
- severity **±1 容忍准确率 ≥85%**，且**severity≥4 真实样本的召回率 ≥95%**（即真实重大事件被判到 ≥4 的比例；这一条对齐 §2.3"重大事件零遗漏"，取代原先与 ±1 口径打架的表述——宁可误报也不漏报重大事件）；
- direction 准确率 ≥80%；
- **编造数字漏杀率 = 0**（所有归一化后仍无法回验的数字卡片必须被降级）。

另：连续 5 个交易日全自动稳定产出；单日 30 只自选股全流程 ≤15 分钟、成本 ≤¥2（AS-5 实测账单随附）。
> 口径说明：§2.3 的"severity≥4 遗漏率 = 0"是**产品级目标**（配合美股 06:00 补采/次日 08:00 合并班次达成），本处的"召回率 ≥95%"是**单模型可验收的工程指标**，二者不再冲突。

### 5.5 M5 决策纪律引擎

**职责**：把"知道"变成"做到"。对抗行为偏差是本模块唯一使命。

**建议单**：策略调仓信号触发时生成：

```python
class TradeProposal(BaseModel):
    id: str; created_at: datetime
    strategy: str; symbol: str; side: Literal["buy","sell"]
    target_weight: float          # 目标仓位
    suggested_shares: int         # 按最新价与仓位规则折算(美股1股/港股按每手lot_size)
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
2. **组合与风控**：持仓/权重/浮盈亏、净值曲线 vs 标普500（港股持仓另叠恒生指数）、回撤水位、风控事件流。
3. **回测实验室**：策略下拉+参数表单+区间选择 → 运行 → 内嵌 BacktestReport（含成本三档与 warnings 显著展示）。
4. **交易台账**：pending proposals（含 checklist 交互）、历史日志、周复盘归档。
5. **设置**：自选股管理、LLM 配置与用量仪表、数据源切换、风控参数、飞书 webhook。

飞书推送固定消息：港股盘后 17:30 简报摘要、美股隔夜 08:00 合并简报摘要（均为 Top3 标题+红旗数+链接）、周一 09:00 周报摘要。推送失败仅记日志不重试轰炸。

**验收标准**：冷启动到简报页首屏 ≤5 秒（数据已就绪前提下）；所有页面在数据缺失日显示明确的降级提示而非报错栈。

### 5.7 M7 调度与运维

APScheduler 进程常驻（`yquant daemon` 命令），时点均为北京时间，锚定各市场收盘、随夏令时自动漂移：**港股交易日 16:30 `update_all`（港股）→ 17:00 港股盘后简报流水线 → 17:30 推送**；**美股隔夜收盘后 06:00 `update_all`（美股，含 EDGAR 盘后 8-K 补采）→ 07:30 隔夜简报流水线 → 08:00 生成隔夜合并视图并推送**；周一 09:00 周报。交易日历判断用 `pandas_market_calendars`（NYSE/NASDAQ/HKEX）落盘的本地日历表。所有任务写 `job_runs` 表（开始/结束/状态/错误摘要），UI 设置页可见最近 20 次。日志用 loguru，按天轮转，保留 30 天。

## 6. 目录结构与工程规范

```
yquant/
├── pyproject.toml            # Poetry;锁定依赖版本
├── config.example.toml       # 全部可配置项与注释;真实config不入库
├── prompts/                  # 版本化prompt: brief_v1.md, review_v1.md
├── yquant/
│   ├── datasrc/               # M1: sources/(yfinance_,akshare_,stooq_,edgar_,hkexnews_), repo.py, quality.py, market_rules.py
│   │                          #   (包内改名为 datasrc/,避免与运行时根目录 data/ 混淆)
│   ├── backtest/             # M2: broker_us.py, broker_hk.py, runner.py, walk_forward.py, report.py
│   ├── strategies/           # M3: base.py, s1_ma_timing.py, s2_dividend_lowvol.py, s3_sector_momentum.py, specs/
│   ├── brief/                # M4: pipeline.py, schemas.py, verifier.py, llm_client.py, input_clip.py
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

**Parquet（列存，DuckDB 查询）**：
- `data/parquet/daily_bars/`（分区键：`market`,`year`；列含 §5.1 `get_bars` 全部字段，含 `adj_factor/is_halted/halt_reason/session`）。
- `data/parquet/index_bars/`（分区键：`index_code`，如 `^GSPC/^NDX/^HSI/^HSTECH`）。
- `data/parquet/financials/`（分区键：`report_period`，即报告期 YYYYMM；**每行必带 `announce_date`（真实或推算）与 `announce_date_estimated` 标记**，这是 T1 前视偏差防护的落盘依据——回测按 `回测日 >= announce_date` 决定该行是否可见；美股取 EDGAR `filed`，港股取 HKEXnews 发布日）。

**SQLite 业务表（DDL 摘要，完整 DDL 交付时给出）**：

```sql
stocks(symbol PK, market, name, exchange, gics_sector, gics_industry_group,
       lot_size, list_date, delist_date, status);   -- market: us/hk
trade_calendar(market, date, is_open, session, PRIMARY KEY(market,date));  -- session: regular/half_day
announcements(id PK, symbol, market, source, filing_type, title, url, pub_time, raw_text, fetched_at);
            -- source: edgar/hkexnews ; filing_type: 8-K/10-Q/10-K/S-1/Form4/HK-业绩公告...
event_cards(id PK, symbol, market, date, source_type, event_type, severity, direction,
            one_line, key_numbers_json, rationale, source_url, unverified,
            input_truncated, batch, prompt_version, created_at);
            -- batch: 简报班次(hk_afterhours_17:00 / us_overnight_0730 / merged_0800)
proposals(id PK, ...同5.5..., checklist_json, decided_at);
trade_log(id PK, proposal_id FK, symbol, side, shares, price, fees, exec_time, note);
portfolio_snapshots(date PK, positions_json, cash, ccy, nav);   -- ccy: USD/HKD
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
| T2 幸存者偏差 | 同一策略分别跑静态现存股票池 vs 动态 `get_universe()` | 两次回测收益差被完整报告；静态池运行时 `warnings` 必含幸存者偏差警告 | 警告存在且动态池含 ≥N 只退市/摘牌股参与过持仓 |
| T3 停牌/停市 | 构造某日 `is_halted=True`（公司停牌）的合成数据+当日买卖信号 | 检查成交记录 | 零成交，拒单入 rejected_orders；持仓按最后有效价估值 |
| T3b 交收周期时变 | 构造 2023 与 2024-06 两个日期的美股买入并次日卖出（跨越 2024-05-28 T+2→T+1 变更点） | 对比两次可用资金到账日 | 2023 用 T+2、2024-06 用 T+1；证明 `market_rules` 按日期时变而非静态表 |
| T4 成本敏感 | 高换手策略（周频满换） | 报告三档成本（含港股印花税/美股 SEC 费+TAF） | 2x 档收益显著低于 0 档，且报告自动生成三档对比 |
| T5 拆股/分红调整 | 含大比例拆股的真实样例（如 AAPL 2020 四拆一、TSLA 五拆一） | 拆股日前后持仓市值连续性 | 净值曲线无跳变（误差<0.1%）；`adjust="adjusted"` 与 `"none"` 口径一致 |
| T6 熔断/波动控制 | 构造美股市场级熔断日（如 2020-03 多次 Level 1）或港股 VCM 冷静期日+当日信号 | 成交记录与成交价 | 成交价被约束在当日 `[low, high]`；越界委托拒单入账 |
| T7 PDT 规则 | 账户 <$25k，5 个滚动交易日内构造第 4 次日内往返（day trade） | 成交记录 | 第 4 次日内开仓被拒并入 rejected_orders；账户≥$25k 时不触发 |

外加确定性测试（同 seed 同结果）与 T0 冒烟（B0 基准年化 ≈ 标普500 实际年化，误差主要来自费用）。

## 9. 里程碑计划（单人外包，兼职口径约 6–9 周）

| 里程碑 | 内容 | 预估人日 | 出口判据（Gate） |
|---|---|---|---|
| M0 环境与假设验证 | 仓库/CI/依赖；AS-1~6 接口与规则实测报告 | 3–4 | assumptions.md 全部落定（含 AS-6 交收周期/费率/微观结构规则与生效时点核对）；yfinance/AkShare/EDGAR/HKEXnews 冒烟通过 |
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

单机部署（家用电脑常开或 2C4G 轻量云主机，约 ¥50–80/月）；LLM 按 §2.3 预算 ≤¥2/日（DeepSeek 档位实测富余，AS-5 外包在 M4 给出实测账单）；行情/公告数据源以免费为主（yfinance/AkShare/Stooq/SEC EDGAR/HKEXnews，均免费），如需商用付费行情源（如 Polygon.io）按需评估（预算 ≤¥500/年，若免费源足够则省略）；无其他付费依赖。

## 11. 风险与合规

- **合规**：系统仅供使用者本人研究与决策辅助，不对外提供投资建议或荐股信号（避免触及投顾监管）；使用 SEC EDGAR / 披露易 HKEXnews 等公开数据须遵守其访问频率与使用条款（EDGAR 要求 User-Agent 标识且限速）；v1.0 不接任何自动下单接口（ADR-09）；若未来评估半自动执行，须另行专项合规评估（icebox）。
- **免责声明**：UI 底部与 README 固定声明"历史回测不代表未来收益，本系统不构成投资建议"。
- **数据风险**：上游接口失效（→多备源+落盘）、字段口径变更（→质检器拦截）。
- **密钥安全**：LLM key、付费数据源 token（如有）、飞书 webhook 全部环境变量注入，仓库含 `.env.example`。
- **技术债红线**：任何"临时绕过陷阱测试"的代码合入均视为验收不通过。

## 12. FAQ（外包开工前必读，预答高频疑问）

**Q1 为什么不用 Qlib？** 我们不做因子研究平台。Qlib 的能力半径与本项目三支柱几乎不重叠，引入只会增加复杂度。见 01 篇 §2.1。
**Q2 为什么 LLM 不直接给买卖建议？这不是 AI 交易系统吗？** 这是本项目最重要的设计决策（ADR-03），完整推理见 02 篇实验 1/3。实现时若发现某处"顺手让 LLM 建议一下"很方便——请不要，这属于 §6 禁止事项。
**Q3 backtrader 停止维护了，要不要换 vectorbt？** 不换。我们是低频策略，backtrader 的成熟度与事件级撮合表达力更匹配；速度瓶颈用"向量化预计算信号 + backtrader 只管撮合"的分层解决，路径见 §5.2 性能实现路径。若实现中遇到无法逾越的框架缺陷，走变更流程（04 §5）。
**Q4 yfinance 某接口挂了/字段变了怎么办？** 这正是适配器模式存在的原因：修对应 adapter 或切备源（AkShare/Stooq），业务层零改动。接口频繁失效本身请记入 assumptions.md 供选型复审。
**Q5 历史公告拿不到全量正文怎么办？** 允许"标题+链接"降级模式，EventCard 打 `unverified`；美股 EDGAR 提供全文（HTML/TXT），港股 HKEXnews 多为 PDF（需解析），正文可得性以 M0 实测为准（AS-1）。长正文的截断策略见 §5.4 输入裁剪策略。
**Q6 评测集谁标注、多少条？** 外包收集素材并预标，委托人终审，争议条目以委托人判定为准。样本量以 §5.4 验收标准为准（≥120 条，严重类目加密），不再是 60 条——小样本统计噪声会让 85% 门槛失真。
**Q7 策略跑不赢标普500，算我做得不好吗？** 不算。验收看的是流程正确与结论诚实（§5.3），负面结论同样是合格交付物，K1 判据正是为此准备的。
**Q8 可以引入 LangChain/LangGraph 吗？** 不建议。M4 是单步结构化任务，裸调 API + pydantic 足够，减少依赖面。若坚持引入需在 PR 中论证收益。
**Q9 时间与时区？** 全系统内部以 UTC 存储、ISO8601 带时区；展示层按北京时间（Asia/Shanghai）渲染；交易日历与班次调度按各市场收盘锚定并随夏令时自动切换（NYSE/NASDAQ/HKEX，见 §5.7）。
**Q10 交付形式？** 见 04 SOW §4：代码仓库 + 全绿 CI + 部署文档（从零到跑通 ≤30 分钟）+ 每里程碑验收演示。

---

*变更管理：对本文档的任何修改需在文末追加变更记录并同步 02 篇 ADR。*

| 版本 | 日期 | 变更 |
|---|---|---|
| v2.0 | 2026-07-05 | 基于 v1 全面重构定位与规格，首次发布 |
| v2.1 | 2026-07-05 | 精确性完善（同步新增 ADR-11~13）：①涨跌停规则改为按日期/板块/ST/新股时变的 `limit_rule`（§5.1/§5.2/§8 T3b），修正静态表在 2016–2020 创业板等区间的历史失真；②M4 新增简报覆盖窗口（17:00/21:30/次日08:30 三班次），修正 17:00 单班次漏晚间公告与"零遗漏"指标的冲突；③M4 新增输入裁剪策略（要素段抽取+左截断+规则前置分类），守住 token 与 ¥2/日 预算；④数字回验由朴素正则改为"归一化后容差比对"，避免误杀正确卡片；⑤M2 补性能实现路径（向量化预计算+backtrader 只撮合），并明确 T+1 需自建持仓批次账本；⑥M4 验收指标口径重定（评测集 ≥120 条；severity≥4 召回率 ≥95% 替代与 ±1 打架的表述）；⑦补细化复用清单、包目录 `datasrc/` 改名、financials 落盘 `announce_date`、event_cards 增 `input_truncated/batch`、质检阈值改为按 `price_limit_pct` 动态。 |
| v2.2 | 2026-07-05 | **研究标的由 A 股整体切换为美股（主）+ 港股（辅），A 股移出范围**（同步 02 篇 ADR-11~13 重述）：①§1/§2 用户画像、用户故事、指标、范围、v1差异表全面改为美股/港股口径（券商富途/老虎/IBKR，基准标普500/恒生）；②§3 架构调度层按各市场收盘锚定重构、M2 改名"美股/港股约束层"、数据流禁直连改为 yfinance/EDGAR；③§4 选型改 yfinance（主）/AkShare/Stooq + SEC EDGAR/HKEXnews，交易日历改 `pandas_market_calendars`，复权改拆股/分红调整，数字归一化改英文量纲；④§5.1 数据基座重写（市场范围/2010至今/GICS 行业/`get_bars` 返回列改 market/is_halted/halt_reason/session、`get_universe` 增 market 参数）；涨跌停规则表**替换为**"交易机制与微观结构规则"表（美股 T+1 交收/LULD/市场级熔断，港股 T+2/VCM/CAS），价格异常检测改用调整后收益跳变；⑤§5.2 broker 改 `broker_us.py/broker_hk.py`：T+1/T+2 交收锁定+PDT 规则取代 A股T+1禁卖、LULD/VCM/停牌撮合取代涨跌停撮合、成本模型改美股(无印花税/SEC费/TAF)+港股(印花税0.1%双边/交易征费)、最小单位改美股1股/港股每手；`BacktestConfig` 增 market 字段、universe 改 all_us/all_hk/all；⑥§5.3 策略改标普500双均线/红利低波/GICS 板块动量，B0 改 SPY；⑦§5.4 班次改港股17:00/美股06:00补采/07:30隔夜/08:00合并，event_type 改美股港股类目并增 market 字段，数字归一化改英文量纲；⑧§7 DDL 增 market/ccy/lot_size/gics 等字段，index_bars 改 ^GSPC/^HSI 等；⑨§8 陷阱测试 T3/T3b/T5/T6/T7 改为停牌/交收周期时变/拆股/熔断/PDT；⑩§9~§12 里程碑 AS-6、成本预算、合规、FAQ 全部对齐美股港股口径与免费数据源。 |
