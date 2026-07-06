# Implementation Log

This log records implementation decisions and verification results. It is not a
product specification; `docs/03_yquant技术方案_v3.1_完整版.md` remains the
authoritative spec.

## 2026-07-06 - WP0a v3.1a Alignment

Baseline:
- Head commit before code alignment: `fc9d9dd`.
- Authoritative docs: v3.1a.
- Active branch: `feat/wp0-foundation`.
- Existing verification state: `pytest` and `ruff` pass; `mypy` fails with 8
  pre-existing type errors.

Why this pass exists:
- Recent commits already added WP0 probes, config, market rules, core strategy
  sketches, M8 risk controls, and M5 discipline logic.
- Those modules were built against an earlier US/HK or v3 draft context.
- v3.1a narrows execution to US stocks and US-listed ETFs, USD accounting, and
  explicit Overlay/icebox guardrails.

Scope for this pass:
- Fix the existing type-checking baseline.
- Move active config defaults toward v3.1a.
- Add pure guardrail logic for Overlay, 2x, 3x/inverse, icebox, and
  discretionary/meme-stock requests.
- Keep historical research notes intact unless they actively mislead runtime
  behavior.

Completed changes:
- Runtime defaults now use `America/New_York`, US-only execution markets, and
  Stooq as the active backup source.
- Risk config now exposes 75/15/10 budgets plus Overlay and 2x caps.
- Active probe CLI was narrowed to yfinance, Stooq, EDGAR, and US calendars.
- Added `yquant.discipline.overlay_guardrails` with tests for ADR-37 and the
  icebox/2x/3x/inverse rules.
- Fixed the pre-existing type errors in probes, proposal construction, strategy
  inference literals, and indicator typing.

Verification:
- `python -m pytest`: 83 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.

Remaining implementation debt:
- Some legacy US/HK-era modules and tests remain in the tree but are no longer
  on the active config/CLI path. They should be either deleted or moved behind
  an explicit legacy/icebox boundary in the next cleanup pass.

## 2026-07-06 - M5 Proposal Guardrail Integration

Baseline:
- Head commit before this pass: `c18ea46`.
- Goal from the staged implementation plan: upgrade M5 proposal/checklist so
  v3.1a guardrails become an actual proposal gate.

Completed changes:
- `TradeProposal` now records layer, instrument kind, system-signal flag,
  machine-readable invalidation condition, and red-team note.
- Proposal creation now requires per-symbol `ProposalMetadata`; missing
  invalidation or red-team fields fail before a proposal is emitted.
- Execution checklist now represents the six v3.1a gates, including layer-budget
  compliance and red-team review.
- Overlay guardrails are wired into proposal creation for buy proposals.
- 2x, 3x, inverse, meme-stock, and discretionary requests are routed to Overlay;
  ordinary systematic core/satellite requests keep their layer.
- Added proposal-level tests for 3x/icebox rejection, 2x single-cap rejection,
  and meme-stock Overlay routing.

Reasoning:
- A rule that exists only as a helper can be bypassed by UI or strategy code.
  The proposal layer is the first durable decision object, so it must be the
  first hard gate.

Remaining implementation debt:
- Proposal rejects are not yet persisted as `risk_event` ledger rows because the
  ledger does not exist yet.
- Checklist state is still a pure object; UI and journal integration come later.
- State-machine gates such as RiskOn/VIX/trend for 2x are not wired yet. This
  pass enforces static budget/instrument gates only.

## 2026-07-06 - Active Scope Cleanup: US-only Execution

Baseline:
- Head commit before this pass: `b1debc4`.
- Goal from the staged implementation plan: remove HK/AkShare/HKEX semantics
  from active code paths while preserving historical research context.

Completed changes:
- Cost model is US-only and tax-free in the active path, matching v3.1a's USD
  execution scope and explicit tax-model exclusion.
- Market rules only accept US aliases and reject HK/other markets.
- EventCard and DataRepo protocol types no longer expose HK as an active market.
- AkShare and HKEX probe modules were removed from `yquant.probes`; their old
  results remain in research as historical context only.
- `WP0_PROBE_FINDINGS.md` now carries a supersession note so old A-share/HK
  probe conclusions are not mistaken for the current plan.
- `poetry.lock` was regenerated after removing inactive datasource dependencies.

Reasoning:
- Keeping inactive markets in active types and tests makes future M1/M2 code
  ambiguous. v3.1a deliberately narrowed execution to US stocks and US-listed
  ETFs, so active code should say "no" early.

Remaining implementation debt:
- Some research files still mention old probes for audit history; that is
  intentional and should not drive implementation.

Non-goals:
- No full M1 data repository.
- No UI.
- No broker automation.
- No LLM production flow.

## 2026-07-06 - M1 Minimum Daily-Bar Data Foundation

Baseline:
- Head commit before this pass: `cd17a8c`.
- Goal from the staged implementation plan: start M1 with a small, testable
  daily-bar foundation instead of wiring strategies directly to yfinance/Stooq.

Completed changes:
- Added a canonical `daily_bars` schema that stores raw and adjusted OHLC prices
  side by side, plus volume, estimated amount, adjustment factor, halt/session
  fields, source, market, and UTC as-of timestamp.
- Added pure normalizers for yfinance and Stooq daily bars. yfinance derives a
  back-adjustment factor from `Adj Close / Close`; Stooq is treated as raw
  unadjusted backup data until a richer adjustment source is introduced.
- Added a `LocalDataRepo` backed by Parquet with append/upsert semantics keyed
  by `symbol/date/source`, and a DataRepo read shape that can return either raw
  or adjusted prices.
- Added lightweight JSONL data manifests with deterministic content hashes.
- Added daily-bar quality checks for required columns, duplicate keys,
  non-positive prices, OHLC range violations, negative volume/amount, and missing
  expected symbols.
- Added offline unit tests for normalization, quality failures, manifest hash
  stability, empty repository reads, Parquet round trip, and upsert behavior.

Reasoning:
- M1 must become the only route into market data. A local normalized store with a
  manifest is the minimum structure needed before M2 backtests, M3 strategies,
  and M9 macro/state logic can be trusted.
- Keeping adapter tests synthetic avoids CI/network flakiness while still
  freezing the source-to-canonical schema contract.

Remaining implementation debt:
- No batch update job, retry/cutover policy, or source freshness report yet.
- No dual-source reconciliation report for yfinance vs Stooq yet.
- Universe membership is still a minimum bar-presence view, not a
  survivorship-safe historical constituent database.
- Macro series, EDGAR documents, SQLite ledger tables, and replay/as-of CLI are
  still future work.

## 2026-07-06 - M1 Daily-Bar Update and Reconciliation Skeleton

Baseline:
- Head commit before this pass: `4e2a28d`.
- Goal from the staged implementation plan: make the daily-bar store usable by
  an operational update path while keeping all network behavior outside unit
  tests.

Completed changes:
- Added `DailyBarsUpdater`, which takes an ordered list of daily-bar sources,
  fetches each symbol, validates canonical quality, falls back to the next
  source on fetch/empty/quality failure, and writes accepted bars to
  `LocalDataRepo`.
- Added source attempt reporting so every symbol/source path records success,
  failure, empty result, or quality failure with row counts and error detail.
- Added cross-source reconciliation for canonical daily bars, comparing raw
  close values by `symbol/date`, reporting missing rows, mismatches in bps, and
  an explicit consistency rate.
- Added `yquant data update` as a thin CLI entry point over config-driven
  yfinance/Stooq source order and the configured Parquet directory.
- Added offline tests for primary-source success, fallback after fetch failure,
  fallback after quality failure, no-write all-failed behavior, reconciliation
  mismatches, missing rows, and CLI parser/source construction.

Reasoning:
- The system needs source fallback before any real daily job is scheduled;
  otherwise transient yfinance/Stooq issues would leak into strategy behavior.
- Reconciliation is kept as a separate pure function so it can later run as a
  sampled quality job without changing the normal update path.

Verification:
- `python -m pytest`: 103 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.
- `python -m yquant data update --help`: passed.

Remaining implementation debt:
- `data update` is intentionally manual; no APScheduler job, trading-calendar
  gating, or close-plus-45-minute freshness SLA yet.
- Reconciliation is not yet persisted as a quality report artifact.
- No retry/backoff policy; current fallback is source-order only.
- No macro/index batch update path yet.

## 2026-07-06 - M1 Quality Artifacts and Freshness Precheck

Baseline:
- Head commit before this pass: `2c6e9b4`.
- Goal from the staged implementation plan: make M1 update outcomes auditable
  before introducing scheduler or ledger persistence.

Completed changes:
- Added generic JSON artifact helpers for M1 report objects. Artifacts include a
  normalized kind, UTC generation timestamp, JSON-safe dataclass payload, and
  computed report fields such as `passed`.
- `yquant data update` now writes a `daily_bars_update` quality artifact under
  `data_dir/quality` by default, with an override via `--quality-dir`.
- Added daily-bar freshness checks over the local `DataRepo`, with per-symbol
  `fresh`, `late`, `stale`, or `missing` statuses.
- Added `yquant data freshness` for local, non-network freshness verification
  against an expected session date and optional UTC deadline.
- Added tests covering artifact serialization, freshness states, CLI parsing,
  and UTC deadline parsing.

Reasoning:
- M1 cannot be considered operational until every data update has a durable
  quality artifact. This creates a handoff point for future M7 scheduling,
  alerting, and incident collection without coupling those modules now.
- Freshness is deliberately checked from the local repository, not by calling
  providers, so it answers "what does the system currently know?" rather than
  "can the internet fetch something now?"

Verification:
- `python -m pytest`: 108 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.
- `python -m yquant data update --help`: passed.
- `python -m yquant data freshness --help`: passed.

Remaining implementation debt:
- Reconciliation reports are still pure objects; they are not yet wired to a
  command or scheduled sampled quality job.
- Freshness deadlines are caller-provided; XNYS calendar close + 45 minute
  deadline calculation is still future work.
- No APScheduler job, retry/backoff, persisted ledger event, or alerting path
  yet.

## 2026-07-06 - M1 Reconciliation CLI and Calendar Freshness Deadline

Baseline:
- Head commit before this pass: `7c709db`.
- Goal from the staged implementation plan: turn reconciliation and freshness
  SLA checks into auditable operator commands with tests and local artifacts.

Completed changes:
- Added `LocalDataRepo.get_daily_bars_storage(...)` so quality jobs can read
  canonical stored rows filtered by source without changing the business-facing
  `DataRepo.get_bars(...)` protocol.
- Added `yquant data reconcile`, which compares persisted daily bars across two
  sources, prints row/mismatch/consistency statistics, and writes a
  `daily_bars_reconciliation` JSON artifact.
- Added `expected_daily_bar_deadline_utc(...)`, deriving a freshness deadline
  from a `pandas_market_calendars` exchange close plus a configurable minute
  offset. `data freshness --use-calendar-deadline` uses this path.
- Calendar-derived deadlines fail with a clear error if
  `pandas_market_calendars` is unavailable, instead of crashing with an import
  traceback.
- Added execution-level CLI test coverage for `data reconcile` using a temporary
  config, temporary Parquet repo, and generated quality artifact.

Reasoning:
- Reconciliation must be an artifact-producing operation, not just an in-memory
  helper, because P3 acceptance depends on leaving evidence behind.
- The freshness SLA belongs to the exchange calendar, not a hardcoded UTC hour.
  Keeping the calendar dependency dynamic preserves testability and makes the
  missing-dependency failure explicit.

Verification:
- `python -m pytest`: 115 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.
- `python -m yquant data reconcile --help`: passed.
- `python -m yquant data freshness --help`: passed.

Remaining implementation debt:
- Reconciliation currently reads already-persisted source rows. A sampled live
  dual-fetch job for P3 still needs orchestration.
- No APScheduler job, retry/backoff, persisted ledger event, or alerting path
  yet.
- Macro/index series still need their own storage schema and update path.

## 2026-07-06 - Sampled Live Dual-Source Reconciliation Job

Baseline:
- Head commit before this pass: `aa06e73`.
- Goal: close the P3-evidence gap noted above by fetching sampled symbols live
  from both sources and reconciling the two live results, instead of only
  comparing rows already persisted by the fallback-based updater.

Completed changes:
- Added `yquant/datasrc/reconcile_live.py`:
  - `sample_symbols(pool, sample_size, seed)` normalizes the pool (upper-cased,
    de-duplicated, sorted) before sampling, so a given seed selects the same
    symbols regardless of input order — reproducible, auditable evidence.
  - `run_sampled_live_reconciliation(...)` queries both sources for every
    sampled symbol without fallback, records a per-source `SourceFetchOutcome`
    (success/empty/failed) instead of short-circuiting, then feeds the combined
    live frames into `reconcile_daily_bars`.
  - `SampledLiveReconciliationReport` wraps the reconciliation with sampling
    metadata (universe size, sample size, seed, sampled symbols) and per-source
    fetch-failure counts; `passed` requires a clean reconciliation *and* no
    fetch failures on either side.
- Added `yquant data reconcile-live`, which samples from an explicit `--symbols`
  pool (or the repo universe on `--on-date` when `--symbols` is omitted),
  supports `--sample-size`/`--seed`/`--request-pause-seconds`, and writes a
  `daily_bars_live_reconciliation` JSON artifact.
- Hardened `reconcile_daily_bars` to return a zeroed report when both sides are
  empty, instead of crashing inside the pandas/pyarrow merge — the common case
  when every live fetch fails or is empty.

Reasoning:
- The updater deliberately stops at the first successful source, so it rarely
  stores both sources for the same day; a dedicated both-source live fetch is
  required to produce genuine cross-source evidence.
- Comparison stays on `close_raw`: Stooq bars are unadjusted and yfinance is
  stored with raw + adjustment factor, so raw-vs-raw is the correct
  apples-to-apples comparison and avoids false mismatches from differing
  corporate-action handling.
- Seeded sampling and recorded metadata make each evidence run re-runnable.

Verification:
- `python -m pytest`: 125 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.
- `python -m yquant data reconcile-live --help`: passed.
- Synthetic happy-path run (fake sources, seed 7) sampled `AAPL, MSFT`, compared
  6 rows, 0 mismatches, consistency 1.0, passed.
- A real CLI run against yfinance/stooq from this restricted environment was
  blocked by the network egress policy (Yahoo `CONNECT` denied, 403); the job
  degraded gracefully — per-source fetch failures were recorded and an artifact
  was still written. A genuine green artifact requires running where egress to
  Yahoo/Stooq is permitted.

Remaining implementation debt:
- No APScheduler job, retry/backoff, persisted ledger event, or alerting path
  yet; the live reconciliation is still a manual operator command.
- Macro/index series still need their own storage schema and update path.
