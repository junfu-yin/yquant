# M1 End-to-End Milestone

Status: implementation-side milestone note, not authoritative product docs
(`docs/` is unchanged).

Date: 2026-07-06

This milestone takes M1 from a set of manual, on-demand data commands to an
unattended, survivorship-aware, risk-gated pipeline with CI. It was built in four
phases on branch `claude/dual-source-reconciliation-sampling-7nd91i`, each landed
green (`pytest` + `ruff` + `mypy`) and pushed separately.

## Baseline

Head before this milestone: `aa06e73` (M1 reconciliation quality workflow). At
that point M1 had canonical storage, yfinance/Stooq normalizers, an ordered
updater with fallback, stored-source reconciliation, freshness checks, and JSON
quality artifacts — all invoked by hand, with no CI, scheduling, alerting, or
survivorship handling.

## Phase 0 — CI regression net (`9b7fc40`)

- `.github/workflows/ci.yml`: `ruff` + `mypy` + `pytest` on every push to `main`
  and every PR, Python 3.11 / Poetry 2.4.1 against the committed lockfile.
- Closes the "no CI" blind spot: the branch is now checked automatically.

## Phase 1 — Ingestion hardening (`f928385`)

- **Ledger** (`yquant/ledger`): SQLite store for `risk_events` and `job_runs`,
  idempotent bootstrap; the shared evidence sink for the scheduler and (Phase 3)
  proposal rejects. Matches the `risk_events(date, rule, detail_json)` shape the
  `RiskEvent` type already targeted.
- **Retry/backoff** (`yquant/datasrc/retry.py`): pure `RetryPolicy` +
  `run_with_retry` with injectable sleep and jitter, wired into `DailyBarsUpdater`
  and the live-reconciliation fetch path. Opt-in; default off preserves behavior.
- **Alerting** (`yquant/notify`): Feishu webhook notifier with an injectable
  transport, plus formatters for freshness / reconcile / live-reconcile failures.
- **Scheduler** (`yquant/scheduler`): `JobContext` + update / freshness /
  reconcile-live jobs that record outcomes in the ledger and alert on failure;
  `build_scheduler` registers cron triggers on APScheduler. Optional `[schedule]`
  config section; `schedule list | run-once | run` CLI.

## Phase 2 — Data correctness (`b3a954e`)

- **Survivorship-safe universe** (`yquant/datasrc/security_master.py`): listing /
  delisting dates make `get_universe(on_date)` point-in-time — it includes names
  that later delisted and excludes not-yet-listed ones — with a bar-presence
  fallback when no master is loaded. CLI: `data load-securities`, `data universe`.
- **Macro/index series** (`yquant/datasrc/macro.py`): canonical long-format
  storage for index and ^VIX levels, a yfinance adapter, `MacroUpdater`, repo
  read/write, and `data update-macro`.
- **As-of replay** (`repo.get_bars_asof`): excludes rows recorded (`asof`) after a
  cutoff so backtests never see future-recorded data. CLI: `data asof`. Limitation
  documented: single-version storage cannot reconstruct overwritten prior
  versions (full bitemporal history is future work).

## Phase 3 — Risk wiring (`0fd5998`)

- **Risk regime** (`yquant/risk/regime.py`): `compute_risk_on` turns a market
  trend flag + VIX level into a `RiskRegime`, degrading to trend-only when VIX is
  unavailable.
- **Dynamic 2x gate**: `validate_overlay_request` refuses a 2x-long overlay in a
  risk-off backdrop; threaded through `build_proposals` via an optional
  `risk_regime`. Backward compatible — no regime means the static caps are
  unchanged.
- **Ledgered rejects** (`yquant/discipline/reject_ledger.py`):
  `record_proposal_rejection` persists guardrail breaches as `proposal_reject:*`
  `risk_events`, one per violation (or a generic event when unstructured).

## Verification

- `python -m pytest`: 174 passed (was 115 at the reconciliation-workflow commit).
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.
- CI green on the PR for each phase.

## Environment caveat (unchanged from the live-reconcile work)

The sandbox network policy denies egress to Yahoo/Stooq, so the live paths
(update, reconcile-live, macro update) and real Feishu delivery cannot be
exercised end-to-end here. They are unit-tested with fakes and degrade gracefully
(failures recorded and, where configured, alerted). Run them where egress is open
to produce real artifacts.

## What is intentionally still open

- Bitemporal bar history for full as-of reconstruction.
- A real security-master / macro source feed behind an adapter (master is
  currently CSV-ingested; macro is yfinance-only).
- Automatic risk-regime computation from stored macro inside the scheduler.
- Daemon retry evidence and alert de-duplication.
