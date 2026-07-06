# WP0a v3.1a Alignment Plan

Status: implementation-side alignment note, not part of `docs/`.

## Current Repository Reality

The repository is no longer documentation-only. The July 5 commits introduced:
- WP0 probe framework and dependency lock files.
- US/HK market rules and probe commands.
- Core strategy sketches: C1, C2, C3.
- Satellite S-A sketch and LLM satellite provider contracts.
- M8 risk mechanisms: trend gate, vol target, circuit breaker, crowding.
- M5 proposal/checklist/risk-rule sketches.

These pieces are useful, but they predate the final v3.1a scope.

## v3.1a Alignment Targets

Runtime defaults:
- Business timezone: `America/New_York`.
- Currency: USD.
- Execution universe: US stocks and US-listed ETFs only.
- Direct HK trading, multi-currency accounting, AkShare/HKEX implementation
  paths: not active scope.

Hard guardrails:
- Core/Satellite/Overlay budgets are 75/15/10.
- Overlay total cap is 10%.
- Overlay single-position cap is 5%.
- 2x long ETF total cap is 5%, single cap is 3%.
- 3x and inverse ETFs are rejected in current scope.
- Icebox tickers are rejected unless a formal change process unlocks them.
- Discretionary, meme-stock, social-hype, and "high confidence" ideas count as
  Overlay; confidence never breaks caps.

## Near-Term Acceptance

WP0a is acceptable when:
- `pytest`, `ruff`, and `mypy` all pass.
- Runtime config defaults match v3.1a.
- Tests cover the guardrails above as pure logic.
- Any remaining US/HK-era code is either removed from active paths or explicitly
  parked as historical/icebox implementation debt.

## 2026-07-06 Status

Done:
- Active runtime config and CLI probe paths match the v3.1a execution domain.
- Overlay/icebox guardrails exist as tested pure logic.
- The full local quality baseline is green.
- M5 proposal creation now requires invalidation/red-team metadata and enforces
  static Overlay/2x/3x/icebox guardrails.
- Active market rules, cost model, EventCard schema, and DataRepo protocol are
  US-only.
- Legacy AkShare/HKEX probe modules were removed from the active package.
- M1 daily-bar minimum foundation now has canonical raw/adjusted storage,
  yfinance/Stooq normalizers, Parquet-backed `LocalDataRepo`, manifest hashes,
  and quality checks.
- M1 daily-bar updates now have a source-ordered updater, manual CLI entry, and
  pure yfinance/Stooq reconciliation report logic.
- M1 daily-bar update and freshness checks now write JSON quality artifacts.
- M1 now exposes operator commands for update, reconciliation, and freshness;
  freshness can derive XNYS close-plus-45-minute deadlines when calendar support
  is installed.

Done (2026-07-06 end-to-end M1 milestone, see `M1_MILESTONE_END_TO_END.md`):
- Proposal rejects are ledgered as `risk_event` rows.
- Dynamic 2x gate (RiskOn from trend + VIX) is wired into the overlay guardrails.
- M1 scheduled update/freshness/reconcile jobs (APScheduler), retry/backoff,
  sampled live reconciliation, survivorship-safe universe, macro series, and
  as-of/replay reads are implemented, with a SQLite ledger, Feishu alerting, and
  CI (ruff/mypy/pytest).

Not done:
- Full bitemporal bar history (as-of currently excludes future-recorded rows but
  cannot reconstruct overwritten versions).
- Real security-master and macro source feeds behind adapters (master is
  CSV-ingested; macro is yfinance-only).
- Automatic risk-regime computation from stored macro inside the scheduler.
