# yquant Implementation Research Notes

Status: working implementation notes, not part of `docs/`.

This file captures implementation judgment, open questions, criticism, and a
practical starting plan. The authoritative product specification remains
`docs/03_yquant技术方案_v2_完整版.md` on the latest accepted branch. This file is
allowed to be opinionated and temporary.

## Current Read

yquant is not an "AI stock picker". The useful product is a local operating
system for one A-share investor:

1. A data and backtest base that refuses to produce misleading numbers.
2. An AI research brief that reads announcements/news and produces traceable
   event cards, not trading advice.
3. A discipline layer that turns strategy signals into proposals, checklists,
   trade logs, and review evidence.

The current repository is documentation-first. That is acceptable, but it means
the first implementation milestone must be engineering setup plus assumption
verification, not feature work.

## Biggest Missing Inputs

### WP0 assumptions

The following must be turned into evidence before deep business code is written:

- AS-1: announcement source, fields, body availability, URL stability, and rate
  behavior.
- AS-2: news source, quality, deduplication behavior, and whether source
  timestamps are trustworthy.
- AS-3: financial data announce dates. If no reliable announce date exists,
  fallback estimation rules must be explicit and marked in data.
- AS-4: delisted stock availability. Dynamic universe quality depends on this.
- AS-5: LLM runtime and cost for a 30-stock watchlist under the clipping policy.
- AS-6: historical price-limit rules by board/date/ST/new-listing period.

These are not paperwork. They decide storage schema, tests, and whether the
backtest results can be trusted.

### Strategy specs

S1/S2/S3 are good product choices, but not yet executable specifications. Before
implementation, each needs edge-case rules:

- exact rebalance calendar and execution date;
- instrument mapping such as index vs ETF code;
- missing data handling;
- insufficient candidate handling;
- financial metric visibility date;
- suspension and limit-up/limit-down behavior at rebalance;
- default parameters and allowed ranges.

### M4 evaluation material

The AI brief engine cannot be judged by eyeballing output. It needs the required
labelled evaluation set early: at least 120 samples with enough severe-event
coverage. Without this, prompt changes will be subjective.

## Implementation Position

Start with WP0 and keep the code boring:

- Python package with typed public interfaces.
- Poetry-style `pyproject.toml`.
- Small modules with explicit boundaries.
- Configuration loaded from file/env, never hard-coded secrets.
- Tests first for pure logic: config, calendar guards, schemas, numeric
  verification, price-limit rules.
- Data-source integrations isolated behind adapters and smoke scripts.

Do not build Streamlit pages first. UI can hide broken assumptions and make the
project feel farther along than it is.

## Criticism / Risk

1. The project has a lot of moving parts for a single-user tool. The only way to
   keep it shippable is to enforce the SOW gates and kill/pivot criteria.
2. M2 performance is a real risk. Full A-share, ten-year, event-driven
   backtrader loops will probably be too slow unless signals are precomputed
   outside backtrader.
3. M4 "zero major-event omissions" is partly a data-source problem, not only an
   LLM problem. Missing upstream announcement content cannot be fixed with
   prompts.
4. backtrader is a pragmatic choice, but its unmaintained status means our A
   share broker layer must be heavily tested and replaceable.
5. If docs continue changing during implementation, code should track stable
   contracts, not every sentence. Useful stable contracts are schemas, public
   interfaces, storage columns, and acceptance tests.

## Open Questions For The Owner

These do not block WP0 scaffolding, but they will block later gates:

1. Is the target runtime Windows, WSL/Linux, or both? The spec says
   Linux/macOS/WSL, but the current workspace is Windows.
2. Which LLM provider should be the default for real testing: DeepSeek, Qwen,
   GLM, or OpenAI-compatible local/proxy endpoint?
3. Will the project eventually be public open source? backtrader GPLv3 matters
   if distribution changes.
4. Do you want the first usable slice to be data/backtest first or daily brief
   first? The spec orders data/backtest first, but the daily brief may produce
   user value sooner.
5. What is the exact first watchlist for M4 cost and quality testing?
6. The current spec's `limit_rule(...) -> pct | None` shape cannot express
   asymmetric main-board IPO-day limits such as +44%/-36%. The code should use a
   richer `PriceLimitRule(up_pct, down_pct)` object internally and keep the
   single-pct function only as a compatibility wrapper.
7. The current machine has Anaconda Python 3.13 available, but no Python 3.11 and
   no Poetry on PATH. WP0 should standardize the supported local setup before
   relying on lockfiles or CI parity.

## Near-Term Build Plan

### Step 1: Engineering foundation

- Add `pyproject.toml`, package structure, tests, ruff/mypy/pytest config.
- Add `config.example.toml` and config loader.
- Add a small CLI with `yquant doctor` to inspect runtime/config paths.
- Add empty module boundaries that match the spec.

### Step 2: Assumption probes

- Add data-source smoke scripts that write evidence under a non-docs runtime
  folder, then summarize manually for later docs updates.
- Probe AkShare/Tushare/BaoStock availability without letting business modules
  import those packages directly.

### Step 3: Pure domain logic

- Implement `limit_rule()` with tests before touching backtrader.
- Implement M4 numeric normalization and verification with tests.
- Implement pydantic schemas for EventCard and TradeProposal.

### Step 4: M1 real implementation

- DataSource protocol.
- DataRepo read interface.
- SQLite schema bootstrap.
- Parquet layout utilities.
- QualityReport model and mock-failure tests.

## Quality Bar

High quality here means the code can say "no" safely:

- no silent stale data;
- no unchecked LLM output;
- no future data in backtests;
- no direct data-source calls from business code;
- no secrets in repo;
- no untested market-rule logic.
