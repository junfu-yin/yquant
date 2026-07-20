# yquant

Local US-equity research copilot and discipline engine.

## Release Status

Current release: **v0.1.0-alpha.1** (`0.1.0a1` package version).

This is a private, single-user, **shadow-only** alpha. It can collect and
validate market data, run deterministic research backtests, exercise risk and
discipline rules, and leave an auditable ledger. It does not place broker orders
and its outputs are not yet approved as actionable trade instructions.

Daily-bar ingestion uses yfinance as the primary source and Nasdaq as the alpha
reconciliation/backup source. The legacy Stooq adapter remains available for
older environments but is no longer the default.

The alpha deliberately keeps these paths out of the release contract:

- automated broker execution;
- 2x, 3x, inverse-ETF, meme-stock, or discretionary trade recommendations;
- LLM-generated position sizing or orders;
- production claims based on the synthetic golden/drill datasets;
- T+1 open execution parity (the current backtest uses same-session adjusted
  closes and emits a visible research-only warning).

---

## 目录

- [环境要求](#环境要求)
- [安装指南](#安装指南)
- [配置说明](#配置说明)
- [快速开始](#快速开始)
- [命令参考](#命令参考)
  - [doctor - 环境检查](#doctor---环境检查)
  - [data - 数据管理](#data---数据管理)
  - [schedule - 调度任务](#schedule---调度任务)
  - [probe - 数据源探测](#probe---数据源探测)
  - [backtest - 回测引擎](#backtest---回测引擎)
  - [qa - 质量门禁](#qa---质量门禁)
  - [paper - 模拟交易验证](#paper---模拟交易验证)
  - [brief - 事件简报](#brief---事件简报)
  - [macro - 宏观雷达](#macro---宏观雷达)
  - [ui - UI演示数据](#ui---ui演示数据)
  - [overlay - 杠杆层验证](#overlay---杠杆层验证)
  - [ops - 运维工具](#ops---运维工具)
  - [governance - 治理面板](#governance---治理面板)
  - [ledger - 决策账本](#ledger---决策账本)
- [典型工作流程](#典型工作流程)
- [质量验证](#质量验证)
- [目录结构](#目录结构)
- [故障排查](#故障排查)

---

## 环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | >= 3.11, < 3.14 | 参考运行时为 3.11 |
| Poetry | >= 1.7.0 | Python 依赖管理工具 |
| 操作系统 | macOS / Linux | Windows 未完整测试 |
| 网络 | 可访问 yfinance / SEC EDGAR | 数据抓取需要外网连接 |

可选环境变量（密钥不写入配置文件）：

| 环境变量 | 用途 |
|----------|------|
| `YQUANT_LLM_API_KEY` | LLM 服务 API Key（DeepSeek 默认） |
| `YQUANT_FEISHU_WEBHOOK` | 飞书机器人 Webhook URL（告警通知） |
| `YQUANT_SEC_USER_AGENT` | SEC EDGAR 访问 User-Agent（建议格式：`Name email@domain.com`） |

---

## 安装指南

### 1. 克隆项目并安装依赖

```bash
git clone <repository-url>
cd yquant

# 安装核心依赖 + 数据源 + 开发依赖
poetry install --with dev,datasource

# 或者使用项目自带的虚拟环境（如果存在）
.venv_test/bin/python --version
```

### 2. 初始化配置

复制示例配置文件并根据需要修改：

```bash
cp config.example.toml config.toml
```

默认配置使用 `data/` 目录作为运行时数据存储，该目录已被 Git 忽略。

### 3. 验证安装

```bash
# 使用 poetry
poetry run yquant doctor

# 或直接使用虚拟环境
.venv_test/bin/python -m yquant doctor
```

正常输出应显示版本、配置路径、时区、数据目录等信息。

---

## 配置说明

配置文件采用 TOML 格式，默认读取 `config.toml` 或 `config.example.toml`。完整配置项如下：

### [runtime] 运行时配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `timezone` | `"America/New_York"` | 业务调度时区（纽约定价，UTC 存储） |
| `data_dir` | `"data"` | 运行时数据根目录 |
| `sqlite_path` | `"data/yquant.db"` | SQLite 决策账本路径 |
| `parquet_dir` | `"data/parquet"` | Parquet 行情数据存储目录 |
| `log_dir` | `"data/logs"` | 日志目录 |

### [data] 数据源配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `markets` | `["us"]` | 支持市场（v3.1a 仅支持美股） |
| `primary_source` | `"yfinance"` | 主数据源 |
| `backup_sources` | `["nasdaq"]` | 备份数据源列表 |
| `history_start` | `"2010-01-01"` | 历史数据起始日期 |

### [llm] LLM 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `provider` | `"deepseek"` | LLM 提供商 |
| `base_url` | `"https://api.deepseek.com"` | API 端点 |
| `model` | `"deepseek-chat"` | 模型名称 |
| `api_key_env` | `"YQUANT_LLM_API_KEY"` | API Key 环境变量名 |
| `timeout_seconds` | `45` | 请求超时（秒） |
| `max_input_chars` | `8000` | 最大输入字符数 |
| `daily_budget_alert_usd` | 可选 | 日消费软告警阈值（USD） |

### [risk] 风险与仓位配置

三层仓位架构：核心 (75%) + 卫星 (15%) + 杠杆层 (10%)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `core_budget` | `0.75` | 核心层仓位预算 |
| `satellite_budget` | `0.15` | 卫星层仓位预算 |
| `overlay_budget` | `0.10` | 杠杆层仓位预算 |
| `single_position_limit` | `0.15` | 单标的仓位上限 |
| `overlay_single_position_limit` | `0.05` | 杠杆层单标的上限 |
| `leveraged_etf_total_limit` | `0.05` | 杠杆 ETF 总仓位上限 |
| `leveraged_etf_single_limit` | `0.03` | 单只杠杆 ETF 上限 |
| `industry_position_limit` | `0.35` | 行业仓位上限 |
| `drawdown_warning` | `0.10` | 回撤预警阈值 (10%) |
| `drawdown_strong_warning` | `0.15` | 回撤强预警阈值 (15%) |
| `cooldown_loss_count` | `3` | 连续亏损冷静期触发次数 |
| `cooldown_trading_days` | `3` | 冷静期交易日数 |

### [cost] 交易成本模型

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `commission_per_trade_usd` | `9.50` | 每笔固定佣金 (USD) |
| `sec_fee_rate` | `0.0000278` | SEC 卖出费率 |
| `finra_taf_per_share` | `0.000166` | FINRA TAF 每股费用 |
| `finra_taf_cap_usd` | `8.30` | FINRA TAF 单笔上限 |
| `slippage_rate_etf` | `0.0005` | ETF 滑点率 (0.05%) |
| `slippage_rate_single` | `0.0010` | 个股滑点率 (0.10%) |

### [notification.feishu] 通知配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `webhook_env` | `"YQUANT_FEISHU_WEBHOOK"` | 飞书 Webhook 环境变量名 |

### [schedule] 调度配置（可选）

所有 `*_cron` 为标准 5 字段 cron 表达式，在 `runtime.timezone` 时区解释。留空则禁用该任务。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `symbols` | `["AAPL", "MSFT", "SPY"]` | 调度监控标的列表 |
| `history_days` | `5` | 每次更新回溯天数 |
| `update_cron` | `"30 17 * * 1-5"` | 行情更新 cron（工作日 17:30 纽约） |
| `freshness_cron` | `"45 17 * * 1-5"` | 新鲜度检查 cron |
| `reconcile_cron` | `"0 18 * * 5"` | 周度对账 cron（周五 18:00） |
| `regime_cron` | `"50 17 * * 1-5"` | 宏观状态机 cron |
| `reconcile_sample_size` | `2` | 对账采样数量 |
| `reconcile_seed` | `7` | 采样随机种子 |
| `minutes_after_close` | `45` | 收盘后延迟分钟数 |
| `calendar` | `"NYSE"` | 交易日历名称 |

---

## 快速开始

```bash
# 1. 检查环境
poetry run yquant doctor

# 2. 拉取示例行情数据（yfinance + nasdaq 双源）
poetry run yquant data update --symbols AAPL,MSFT,SPY --start 2024-01-02 --end 2024-01-12

# 3. 检查数据新鲜度
poetry run yquant data freshness --symbols AAPL,MSFT,SPY --expected-date 2024-01-12

# 4. 运行确定性回测
poetry run yquant backtest --symbols SPY --start 2024-01-02 --end 2024-01-12

# 5. 运行质量红黄绿线检查
poetry run yquant qa redlines
```

Runtime data, SQLite ledgers, quality artifacts, and logs are written below
`data/` by the example configuration and are ignored by Git.

---

## 命令参考

所有命令通过 `yquant` 入口调用，通用格式：

```bash
yquant <command> <subcommand> [options]
```

查看所有命令帮助：

```bash
yquant --help
yquant <command> --help
```

---

### doctor - 环境检查

检查运行时环境和配置有效性。

```bash
yquant doctor [--config CONFIG_PATH]
```

**选项：**
- `--config`: 配置文件路径，默认 `config.example.toml`

**输出内容：**
- 版本号、发布渠道、执行模式
- 配置文件路径、时区、数据目录、SQLite 路径
- 市场配置、主/备数据源
- LLM 提供商/模型、API Key 环境变量是否存在
- 飞书 Webhook 环境变量是否存在

**退出码：**
- `0`: 配置加载成功
- `2`: 配置错误

**示例：**
```bash
yquant doctor
yquant doctor --config ./my-config.toml
```

---

### data - 数据管理

数据子命令组，负责行情数据的拉取、对账、检查、Point-in-Time 读取等。

#### data update - 拉取日线行情

从主备数据源抓取并持久化日线数据，支持双源容错和质量校验。

```bash
yquant data update \
  --symbols SYMBOLS \
  --start START_DATE \
  --end END_DATE \
  [--config CONFIG_PATH] \
  [--quality-dir QUALITY_DIR]
```

**必填参数：**
- `--symbols`: 逗号分隔的美股代码，如 `AAPL,MSFT,SPY`
- `--start`: 起始日期（含），格式 `YYYY-MM-DD`
- `--end`: 结束日期（含），格式 `YYYY-MM-DD`

**可选参数：**
- `--config`: 配置文件路径
- `--quality-dir`: 质量报告输出目录，默认 `data/quality`

**输出内容：**
- 每个标的每个数据源的尝试状态、行数、错误信息、质量问题
- DataManifest 清单及存储路径
- 质量工件 (JSON) 路径

**退出码：**
- `0`: 全部标的成功
- `1`: 存在失败标的
- `2`: 参数或配置错误

**示例：**
```bash
# 拉取多只 ETF
yquant data update --symbols SPY,QQQ,TLT,GLD --start 2023-01-01 --end 2024-06-30

# 指定配置和输出目录
yquant data update --symbols AAPL \
  --start 2024-01-01 --end 2024-06-30 \
  --config ./config.toml \
  --quality-dir ./reports/quality
```

#### data freshness - 数据新鲜度检查

检查本地日线数据是否已更新到期望的交易日。

```bash
yquant data freshness \
  --symbols SYMBOLS \
  --expected-date EXPECTED_DATE \
  [--config CONFIG_PATH] \
  [--deadline-utc DEADLINE_UTC] \
  [--use-calendar-deadline] \
  [--minutes-after-close MINUTES] \
  [--calendar CALENDAR_NAME] \
  [--lookback-days DAYS] \
  [--quality-dir QUALITY_DIR]
```

**必填参数：**
- `--symbols`: 逗号分隔的代码列表
- `--expected-date`: 期望的行情日期，`YYYY-MM-DD`

**可选参数：**
- `--deadline-utc`: 手动指定 UTC 截止时间，ISO 格式
- `--use-calendar-deadline`: 根据交易所收盘时间自动推导截止时间（二选一）
- `--minutes-after-close`: 收盘后多少分钟视为截止，默认 45
- `--calendar`: 交易日历，默认 `NYSE`
- `--lookback-days`: 回溯搜索天数，默认 10

**退出码：**
- `0`: 新鲜度检查通过
- `1`: 数据滞后或缺失
- `2`: 参数错误

**示例：**
```bash
# 使用交易所日历自动截止（收盘后45分钟）
yquant data freshness --symbols SPY,QQQ \
  --expected-date 2024-06-28 \
  --use-calendar-deadline

# 手动指定截止时间
yquant data freshness --symbols AAPL \
  --expected-date 2024-06-28 \
  --deadline-utc 2024-06-28T22:00:00Z
```

#### data reconcile - 本地数据对账

比较本地存储中两个数据源的日线数据一致性。

```bash
yquant data reconcile \
  --symbols SYMBOLS \
  --start START_DATE \
  --end END_DATE \
  [--left-source SOURCE] \
  [--right-source SOURCE] \
  [--price-column COLUMN] \
  [--tolerance-bps BPS] \
  [--minimum-consistency-rate RATE]
```

**参数默认值：**
- `--left-source`: `yfinance`
- `--right-source`: `nasdaq`
- `--price-column`: `close_raw`
- `--tolerance-bps`: `10.0`（价格容忍偏差，基点）
- `--minimum-consistency-rate`: `0.995`（最低一致率 99.5%）

**退出码：**
- `0`: 对账通过（一致率达标）
- `1`: 对账失败（存在 mismatch 或一致率不足）
- `2`: 参数错误

**示例：**
```bash
yquant data reconcile \
  --symbols SPY,AAPL,MSFT \
  --start 2024-01-01 --end 2024-06-30 \
  --tolerance-bps 15
```

#### data reconcile-live - 实时拉取对账

实时从双源拉取数据并对账，支持随机采样。

```bash
yquant data reconcile-live \
  --start START_DATE \
  --end END_DATE \
  [--symbols SYMBOLS] \
  [--on-date ASOF_DATE] \
  [--sample-size N] \
  [--seed N] \
  [--request-pause-seconds SECONDS]
```

与 `reconcile` 类似，但数据直接从网络拉取而非本地读取。未指定 `--symbols` 时从本地 universe 采样。

**示例：**
```bash
# 从本地universe随机采样10只标的做周度对账
yquant data reconcile-live \
  --start 2024-06-01 --end 2024-06-28 \
  --sample-size 10 --seed 42 \
  --request-pause-seconds 1.0
```

#### data load-securities - 加载证券主数据

加载 survivorship-bias-free 的证券主数据 CSV。

```bash
yquant data load-securities --csv CSV_PATH [--config CONFIG_PATH]
```

CSV 格式要求：列包括 `symbol`, `market`, `listing_date[, delisting_date]`。

#### data universe - 查询可交易标的池

查看某个时点的 Point-in-Time 可交易标的列表。

```bash
yquant data universe --on-date DATE [--market us|all]
```

**示例：**
```bash
yquant data universe --on-date 2024-01-15 --market us
```

#### data update-macro - 更新宏观/指数数据

拉取宏观经济指标和指数序列。

```bash
yquant data update-macro \
  --series SERIES_IDS \
  --start START_DATE \
  --end END_DATE
```

**示例：**
```bash
yquant data update-macro \
  --series ^GSPC,^VIX,BAMLH0A0HYM2 \
  --start 2023-01-01 --end 2024-06-30
```

#### data asof - Point-in-Time 数据回放

按指定时间点读取当时"已知"的数据，防止未来函数 (lookahead bias)。支持日线和宏观序列。

```bash
yquant data asof \
  --start START_DATE \
  --end END_DATE \
  --as-of-utc UTC_TIMESTAMP \
  [--symbols SYMBOLS] \
  [--series SERIES_IDS] \
  [--adjust none|adjusted]
```

**示例：**
```bash
# 查看2024年2月1日凌晨0点45分可见的SPY/VIX数据
yquant data asof \
  --symbols SPY \
  --series ^VIX \
  --start 2024-01-01 --end 2024-01-31 \
  --as-of-utc 2024-02-01T00:45:00Z
```

---

### schedule - 调度任务

调度子命令组用于无人值守的数据作业管理。

#### schedule list - 列出调度配置

```bash
yquant schedule list [--config CONFIG_PATH]
```

显示配置的 cron 表达式、标的列表、历史天数等。

#### schedule run-once - 立即运行一次任务

```bash
yquant schedule run-once --job JOB_NAME [--on-date DATE]
```

**JOB_NAME 可选值：**
- `update`: 行情更新
- `freshness`: 新鲜度检查
- `reconcile-live`: 实时对账

**退出码：**
- `0`: 任务成功
- `1`: 任务执行失败
- `2`: 参数错误

**示例：**
```bash
yquant schedule run-once --job update
yquant schedule run-once --job freshness --on-date 2024-06-28
```

#### schedule run - 启动调度守护进程

按配置的 cron 表达式阻塞运行调度器，按 Ctrl+C 停止。

```bash
yquant schedule run [--config CONFIG_PATH]
```

---

### probe - 数据源探测

独立探测各数据源可用性，输出 JSON 证据文件到 `data/probes/`。

```bash
yquant probe <probe_name> [options]
```

#### probe yfinance - 探测 yfinance

```bash
yquant probe yfinance [--us-symbol AAPL] [--index-symbol ^GSPC]
```

#### probe stooq - 探测 Stooq

```bash
yquant probe stooq [--us-symbol AAPL] [--index-symbol ^SPX]
```

#### probe edgar - 探测 SEC EDGAR

```bash
yquant probe edgar [--symbol AAPL] [--user-agent-env YQUANT_SEC_USER_AGENT]
```

EDGAR 要求 fair-access User-Agent，需通过环境变量传递。

#### probe calendar - 探测交易日历

```bash
yquant probe calendar [--start 2024-01-01] [--end 2024-01-31]
```

#### probe all - 探测所有数据源

依次探测上述所有源，每个子进程独立超时。

```bash
yquant probe all [--us-symbol AAPL] [--index-symbol ^GSPC] [--timeout-seconds 180]
```

---

### backtest - 回测引擎

运行确定性事件驱动回测，输出完整报告。引擎保证 bit 级可复现，支持 T+1 交收、整股交易、GFV 违规计数、精确成本模型。

```bash
yquant backtest \
  --symbols SYMBOLS \
  --start START_DATE \
  --end END_DATE \
  [--weights WEIGHTS] \
  [--initial-cash AMOUNT] \
  [--benchmark BENCHMARK] \
  [--single-stocks SUBSET] \
  [--output OUTPUT_PATH]
```

**必填参数：**
- `--symbols`: 逗号分隔的标的列表
- `--start`, `--end`: 回测日期范围

**可选参数：**
- `--weights`: 逗号分隔权重，与 symbols 一一对应；默认等权重；权重必须非负、有限、总和≤1
- `--initial-cash`: 初始资金 USD，默认 100,000；必须为正有限值
- `--benchmark`: 基准代码，默认 `SPY`
- `--single-stocks`: 子集标记为个股（使用个股滑点档），其余默认 ETF 档
- `--output`: JSON 报告输出路径（原子写入）

**输出内容：**
- 策略 digest（SHA-256，可复现性验证）
- 核心指标：total_return, annualized_return, max_drawdown, gfv_count
- 基准对比
- 0x/1x/2x 三档成本敏感性分析
- 警告和拒绝交易记录

**退出码：**
- `0`: 回测成功（即使有警告）
- `1`: 无行情数据
- `2`: 参数错误

**示例：**
```bash
# 简单单标的买入持有
yquant backtest --symbols SPY --start 2023-01-01 --end 2024-06-30

# 多标的等权对比SPY基准
yquant backtest \
  --symbols SPY,QQQ,TLT,GLD \
  --start 2022-01-01 --end 2024-06-30 \
  --initial-cash 50000 \
  --benchmark SPY \
  --output ./reports/balanced_backtest.json

# 指定权重，标记个股（使用更高滑点）
yquant backtest \
  --symbols SPY,QQQ,AAPL,MSFT \
  --weights 0.4,0.3,0.15,0.15 \
  --start 2023-01-01 --end 2024-06-30 \
  --single-stocks AAPL,MSFT \
  --output ./report.json
```

---

### qa - 质量门禁

QA 子命令组提供脚本化的质量指标验证，覆盖 P1-P11 指标体系和金窗回归。

#### qa golden - 查看金窗哈希

打印冻结的金窗（golden window）内容哈希和清单。

```bash
yquant qa golden [--window WINDOW_KEY|all]
```

**可用金窗：**
- `2020_covid`: 2020年新冠崩盘及恢复期

**示例：**
```bash
yquant qa golden --window all
yquant qa golden --window 2020_covid
```

#### qa panel - P指标面板

在金窗上运行完整 P-metrics 面板（P1 资金守恒 / P2 NAV双重计算 / P3 源一致性 / P4 价格连续性 / P6 digest可复现 / P10 状态机可用性 / P11 分层预算）。

```bash
yquant qa panel [--window 2020_covid] [--initial-cash 50000] [--output PATH]
```

输出绿/黄/红面板，逐项指标状态。

#### qa drills - 演练台账

运行四个历史事件回放 + 一个消防演练。演练结果是过程检查而非业绩承诺（contaminated data）。

```bash
yquant qa drills [--output PATH]
```

#### qa redlines - 红线验证

重新验证五条合约红线（WP6 每日 P0 清证明）：

- R1: 资金守恒（P1）
- R2: Digest 可复现（P6）
- R3: 双引擎 parity（T7）
- R4: 状态机可用性（P10）
- R5: 分层预算约束（P11）

```bash
yquant qa redlines [--output PATH]
```

全部 PASS 则为绿。红线失败意味着发布契约被破坏。

**示例：**
```bash
# 完整红线验证
yquant qa redlines
```

---

### paper - 模拟交易验证

运行 L1/L2 模拟路径：T7 双引擎 parity 验证 + 影子报告。对比回测引擎与模拟经纪商在同一数据流上的结果，确保行为一致。

```bash
yquant paper \
  [--window 2020_covid] \
  [--initial-cash 50000] \
  [--min-sessions 20] \
  [--output PATH]
```

**参数说明：**
- `--min-sessions`: L1 影子门禁最低会话数，默认 20

**输出内容：**
- 会话数
- Parity 偏差：max_daily_bps（默认 ≤1bps）、cumulative_bps
- Digest 匹配情况
- 对账越界数
- 最终 PASS/FAIL 判定

**退出码：**
- `0`: Parity 验证通过
- `1`: Parity 越界
- `2`: 参数错误

---

### brief - 事件简报

个股事件卡片管道：SEC EDGAR Form 4 内部人交易解析 + 评估集验证。

#### brief eval - 评估集验证

运行冻结的 120 份英文文件评估集，输出评分卡。

```bash
yquant brief eval [--output PATH]
```

**输出指标：**
- 分类准确率（≥85%）
- 严重度偏差在一级内比例（≥85%）
- 高严重度召回率（≥95%）
- 方向准确率（≥80%）
- Trap 误计数（P5 要求 = 0）

---

### macro - 宏观雷达

宏观雷达模块：鹰派/鸽派情绪校准 + 委员会护栏。

#### macro calibrate - 鹰鸽校准

运行冻结的 30 句五档鹰鸽校准集。

```bash
yquant macro calibrate [--output PATH]
```

**输出指标：**
- 平均绝对偏差（<0.5 档）
- 方向准确率
- 偏差在一级内比例

---

### ui - UI演示数据

生成六页驾驶舱的确定性演示 payload（LLM-free，可复现）。

#### ui demo - 生成演示数据

```bash
yquant ui demo [--output PATH]
```

输出内容对应六页 UI：
- US-1 今日简报：天气状态、事件卡、Top3
- US-2/4 机会与风险：机会簿、Overlay合计、哨兵触发
- US-3 交易台账：已执行/拦截数、平均滑点
- US-3 组合与风控：Overlay越界标志
- US-6 回测实验室：成本档、SPY对照、walk-forward槽位

---

### overlay - 杠杆层验证

2x 杠杆条款验证 + 纸面机会簿回放（WP16）。

#### overlay paper-book - 机会簿回放

在冻结影子窗口上回放机会簿，统计进入/失效/过期/仍持仓数量。

```bash
yquant overlay paper-book [--output PATH]
```

---

### ops - 运维工具

运维子命令组：runbook、分层区间簿、每日 Owner 检查。

#### ops daily-check - 五分钟日检

运行确定性的 Owner 五分钟日检（08 §7）。所有项 fail-closed，空输入不造假绿。

```bash
yquant ops daily-check [--output PATH]
```

检查项包括数据新鲜度、P-metrics、Overlay权重合法性等。输出每项 [OK/!!] 状态和 runbook 引用。

#### ops interval-book - 分层区间簿

基于 walk-forward 构建第一个分层区间簿实例（08 §4）。Core/S-A 独立生成 OOS band，非复制。

```bash
yquant ops interval-book [--output PATH]
```

输出各策略层（core/satellite/overlay）的 p10/p50/p90 业绩分位带和硬上限。

#### ops runbook - 可机读 Runbook

输出机器可读运维手册并验证告警绑定完整性。

```bash
yquant ops runbook [--output PATH]
```

列出所有 runbook 章节、严重度提示，并检查是否有告警绑定缺口。

---

### governance - 治理面板

注册 provider 四件套面板 + 污染门控。

#### governance panel - 治理面板

```bash
yquant governance panel [--output PATH]
```

输出各 provider 的四件状态（数据质量/OOD/PSI/block状态）、污染标记、被阻止 provider 列表，以及 thesis sentinel 召回率。

---

### ledger - 决策账本

检查和审计 SQLite 决策事件账本。

#### ledger replay - 回放验证

重放计算 run digest 并验证与记录值一致。

```bash
yquant ledger replay --run-id RUN_ID [--strict] [--config CONFIG_PATH]
```

**参数：**
- `--run-id`: 要回放的运行 ID
- `--strict`: digest 不匹配或出处漂移时返回退出码 1

**输出：**
- 事件数、记录 digest、重算 digest、一致性结果
- 出处警告、首次分歧位置

#### ledger collect - 事故证据收集

为某次运行收集事故证据包。

```bash
yquant ledger collect --run-id RUN_ID [--output PATH]
```

#### ledger chain - 因果链追溯

追溯某个事件的完整因果链。

```bash
yquant ledger chain --event-id EVENT_ID
```

输出从叶子事件到根因的完整事件链。

---

## 典型工作流程

### 流程一：首次安装后的最小验证路径

```bash
# 1. 安装
poetry install --with dev,datasource

# 2. 环境检查
poetry run yquant doctor

# 3. 探测数据源连通性
poetry run yquant probe all

# 4. 拉取小范围数据
poetry run yquant data update \
  --symbols SPY,QQQ,TLT,GLD,AAPL,MSFT \
  --start 2024-01-02 --end 2024-03-31

# 5. 新鲜度检查
poetry run yquant data freshness \
  --symbols SPY,QQQ,TLT,GLD \
  --expected-date 2024-03-28 \
  --use-calendar-deadline

# 6. 简单回测
poetry run yquant backtest \
  --symbols SPY,QQQ,TLT,GLD \
  --weights 0.5,0.2,0.2,0.1 \
  --start 2024-01-02 --end 2024-03-28

# 7. 红线门禁
poetry run yquant qa redlines
```

### 流程二：每日收盘后作业

```bash
# 1. 行情更新（使用调度配置）
poetry run yquant schedule run-once --job update

# 2. 新鲜度检查
poetry run yquant schedule run-once --job freshness

# 3. 日检
poetry run yquant ops daily-check

# 4. 红线验证
poetry run yquant qa redlines
```

### 流程三：周度对账与治理

```bash
# 周五下午执行
poetry run yquant schedule run-once --job reconcile-live

# 治理面板
poetry run yquant governance panel

# 区间簿更新
poetry run yquant ops interval-book
```

### 流程四：研究回测工作流

```bash
# 1. 拉取足够历史数据（至少3-5年）
poetry run yquant data update \
  --symbols SPY,QQQ,IWM,TLT,GLD,DBC,EEM,XLK,XLF,XLE \
  --start 2018-01-01 --end 2024-06-30

# 2. 数据对账确认质量
poetry run yquant data reconcile \
  --symbols SPY,QQQ,IWM,TLT,GLD \
  --start 2018-01-01 --end 2024-06-30

# 3. 运行回测（保存JSON报告）
poetry run yquant backtest \
  --symbols SPY,QQQ,TLT,GLD \
  --weights 0.5,0.2,0.2,0.1 \
  --start 2018-01-01 --end 2024-06-30 \
  --initial-cash 100000 \
  --benchmark SPY \
  --output ./research/balanced_6y.json

# 4. P指标面板验证
poetry run yquant qa panel --window 2020_covid

# 5. 双引擎parity验证
poetry run yquant paper --window 2020_covid
```

---

## 质量验证

### Alpha Verification

The release gate is:

```bash
poetry run ruff check .
poetry run mypy yquant tests scripts
poetry run pytest --cov=yquant --cov-report=term-missing --cov-fail-under=90
poetry run python scripts/mutation_check.py
poetry run python scripts/chaos_drill.py
```

See `research/RELEASE_V0_1_ALPHA.md` for the release boundary, verification
evidence, known limitations, and the promotion gate for v0.1.

### 测试套件说明

| 测试类型 | 命令 | 说明 |
|----------|------|------|
| 全量单元测试 | `pytest tests/unit/ -v` | 641 个单元测试 |
| 陷阱/演练测试 | `pytest tests/traps/ -v` | 17 个陷阱/历史事件测试 |
| 覆盖率检查 | `pytest --cov=yquant --cov-report=term-missing` | 要求 ≥90% |
| 静态检查 Ruff | `ruff check .` | 代码风格、import 排序、常见错误 |
| 类型检查 Mypy | `mypy yquant tests scripts` | 严格类型检查 |
| 编译检查 | `python -m compileall -q yquant scripts` | 语法验证 |
| 变异测试 | `python scripts/mutation_check.py` | 12/12 mutants killed 标准 |
| 混沌演练 | `python scripts/chaos_drill.py` | 4/4 异常场景优雅处理 |

---

## 目录结构

```
yquant/
├── yquant/                    # 主源码包
│   ├── backtest/              # M2 回测引擎
│   │   ├── engine.py          # 确定性事件循环
│   │   ├── costs.py           # US 成本模型（佣金/Slippage/SEC/FINRA）
│   │   ├── report.py          # 报告生成（0/1x/2x成本、SPY基准）
│   │   └── walkforward.py     # Walk-forward 验证
│   ├── datasrc/               # M1 数据层
│   │   ├── repo.py            # Parquet 本地仓库（PIT版本、文件锁、原子写）
│   │   ├── update.py          # 日线更新器
│   │   ├── reconcile.py       # 双源对账
│   │   ├── sources.py         # 数据源构建（yfinance/nasdaq/stooq）
│   │   └── macro.py           # 宏观数据更新
│   ├── risk/                  # M8 风险引擎
│   │   ├── state_machine.py   # Regime状态机（RiskOn/Neutral/RiskOff/Crisis）
│   │   ├── regime_gate.py     # Regime Gate（缩仓/减半）
│   │   ├── vol_target.py      # 波动率目标
│   │   └── types.py           # 风险配置类型
│   ├── discipline/            # 交易纪律层
│   │   ├── overlay_guardrails.py # Overlay三层护栏
│   │   ├── proposals.py       # 提案构建
│   │   └── risk_rules.py      # 风险规则执行
│   ├── overlay/               # 杠杆层
│   │   ├── leverage.py        # 2x 三条件门控
│   │   └── paper_book.py      # 纸面机会簿
│   ├── paper/                 # 模拟经纪商
│   │   ├── broker.py          # PaperBroker（重复/倒序会话拒绝）
│   │   ├── execution.py       # 成交模拟
│   │   └── parity.py          # T7 双引擎 parity 验证
│   ├── strategies/            # 策略
│   │   ├── base.py            # TargetPortfolio基类（NaN/权重校验）
│   │   ├── core/              # 核心策略（多资产双动量等）
│   │   └── satellite/         # 卫星策略（板块动量等）
│   ├── macro/                 # M9 宏观
│   │   ├── committee.py       # 委员会预算与红队
│   │   ├── hawk_dove.py       # 鹰派/鸽派情绪
│   │   └── schemas.py         # 宏观条件解析（防回退）
│   ├── governance/            # 治理
│   │   ├── blackbox.py        # FeatureDrift/PSI/OOD 阈值
│   │   ├── evaluation.py      # 评估指标
│   │   └── panel.py           # Provider 四件面板
│   ├── brief/                 # M4 事件简报
│   │   ├── filings.py         # Form4 解析
│   │   └── eval.py            # 评估集验证
│   ├── ledger/                # 决策账本
│   │   ├── store.py           # SQLite 存储（并发幂等upsert）
│   │   ├── replay.py          # Digest 回放验证
│   │   └── incident.py        # 事故证据收集
│   ├── scheduler/             # 调度器
│   │   └── jobs.py            # APScheduler 封装（时区正确日期）
│   ├── probes/                # WP0 数据源探测
│   ├── qa/                    # QA 质量体系
│   │   ├── metrics.py         # P1-P11 指标
│   │   ├── redlines.py        # 五条红线
│   │   ├── panel.py           # 指标面板
│   │   └── drills.py          # 演练台账
│   ├── ops/                   # 运维工具
│   │   ├── daily_check.py     # 五分钟日检（fail-closed）
│   │   ├── interval_book.py   # 分层区间簿
│   │   └── runbook.py         # 可机读 runbook
│   ├── notify/                # 通知
│   │   └── feishu.py          # 飞书机器人（HTTPS校验、best effort）
│   ├── ui/                    # UI视图模型
│   ├── cli.py                 # CLI 入口
│   └── config.py              # 配置加载与校验
├── scripts/                   # 运维脚本
│   ├── mutation_check.py      # 变异测试（隔离workspace、timeout）
│   └── chaos_drill.py         # 混沌演练
├── tests/
│   ├── unit/                  # 单元测试（641个）
│   └── traps/                 # 陷阱/演练测试（17个）
├── docs/                      # 设计文档（12篇SSOT）
├── research/                  # 研究记录和发布材料
├── data/                      # 运行时数据（Git忽略）
│   ├── parquet/               # Parquet行情数据
│   ├── quality/               # 质量工件
│   ├── probes/                # 探测结果
│   ├── logs/                  # 日志
│   └── yquant.db              # SQLite决策账本
├── config.example.toml        # 示例配置
├── pyproject.toml             # Poetry 项目配置
└── README.md                  # 本文件
```

---

## 故障排查

### 常见问题

**Q: poetry install 失败，提示 `poetry: command not found`**

A: 使用项目自带虚拟环境：
```bash
.venv_test/bin/python -m pip list
.venv_test/bin/python -m yquant doctor
```

**Q: yfinance 拉取数据超时或失败**

A: 1. 检查网络连接；2. 使用 probe 诊断：
```bash
yquant probe yfinance
```
系统会自动 fallback 到 nasdaq 备份源。

**Q: SEC EDGAR 访问返回 403 Forbidden**

A: EDGAR 要求合规的 User-Agent。设置环境变量：
```bash
export YQUANT_SEC_USER_AGENT="Your Name your.email@example.com"
yquant probe edgar
```

**Q: 回测报错 "no bars found for the requested range"**

A: 先拉取对应时间范围的数据：
```bash
yquant data update --symbols YOUR_SYMBOLS --start START --end END
```

**Q: 飞书通知不工作**

A: 1. 确认环境变量已设置并指向 HTTPS URL；2. 飞书通知是 best-effort，发送失败仅记 warning，不阻断主任务。

**Q: 如何确认双源数据一致？**

A: 运行对账：
```bash
yquant data reconcile --symbols SPY,QQQ --start 2024-01-01 --end 2024-06-30
```
一致率 ≥99.5% 视为通过。

**Q: 回测结果可复现吗？**

A: 是。回测引擎是纯确定性的：
- 给定相同 bars 和 target_provider，产生相同的 SHA-256 digest
- 可通过 `yquant qa panel` 中的 P6 验证：运行两次结果必须一致

**Q: data asof 有什么用？**

A: 防止未来函数。例如你在 2024-02-01 做研究，你只能看到 2024-01-31 收盘前的数据。`asof` 可以按任意时间点回放当时可见的数据，防止误用后来修正过的数据。

### 诊断命令清单

| 目的 | 命令 |
|------|------|
| 环境检查 | `yquant doctor` |
| 数据源可用性 | `yquant probe all` |
| 数据新鲜度 | `yquant data freshness ... --use-calendar-deadline` |
| 数据质量对账 | `yquant data reconcile ...` |
| 合约红线验证 | `yquant qa redlines` |
| P指标面板 | `yquant qa panel` |
| 双引擎 parity | `yquant paper` |
| 日检 | `yquant ops daily-check` |
| 账本回放 | `yquant ledger replay --run-id ID --strict` |

---

## 文档索引

详细设计文档参见 [docs/](docs/) 目录（12篇作为单一事实来源 SSOT）：

- [01_开源竞品调研与生态位分析.md](docs/01_开源竞品调研与生态位分析.md)
- [02A_ADR汇总与状态表.md](docs/02A_ADR汇总与状态表.md)
- [03_yquant技术方案_v3.1_完整版.md](docs/03_yquant技术方案_v3.1_完整版.md)
- [04_SOW工作包总表_v3.1.md](docs/04_SOW工作包总表_v3.1.md)
- [06_测试与质量保障_v3.1.md](docs/06_测试与质量保障_v3.1.md)
- [07_可观测性_审计与回放_v3.1.md](docs/07_可观测性_审计与回放_v3.1.md)
- [08_上线阶梯_v3.1.md](docs/08_上线阶梯_v3.1.md)
- [09_模型评估与可解释性_v3.1.md](docs/09_模型评估与可解释性_v3.1.md)
