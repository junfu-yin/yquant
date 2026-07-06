# M1 Implementation Status

Status: implementation-side note, not authoritative product docs.

## Current Scope

M1 currently covers US daily bars only:
- yfinance primary and Stooq backup normalizers.
- Canonical raw/adjusted OHLC storage.
- Local Parquet-backed `LocalDataRepo`.
- JSONL manifests for written daily-bar slices.
- Source-ordered update with fallback.
- Stored-source reconciliation.
- Sampled live dual-source reconciliation (both sources fetched, no fallback).
- Retry/backoff policy around source fetches (update and live reconciliation).
- Local freshness checks.
- JSON quality artifacts under `data/quality` by default.
- SQLite ledger for `risk_events` and `job_runs`.
- Feishu alerting on freshness/reconciliation failure.
- APScheduler daemon running update/freshness/reconcile-live on cron.
- Survivorship-safe point-in-time universe from a security master.
- Macro/index level series storage and update.
- Point-in-time (as-of) bar reads as a backtest lookahead guard.
- Dynamic 2x-long leverage gate (RiskOn from trend + VIX) and ledgered
  proposal rejections.

## Operator Commands

Manual daily-bar update:
```powershell
python -m yquant data update --symbols AAPL,MSFT,SPY --start 2024-01-01 --end 2024-01-31
```

Compare persisted yfinance vs Stooq rows:
```powershell
python -m yquant data reconcile --symbols AAPL,MSFT --start 2024-01-01 --end 2024-01-31
```

Sample symbols and reconcile fresh live yfinance vs Stooq fetches (P3 evidence):
```powershell
python -m yquant data reconcile-live --symbols AAPL,MSFT,SPY --start 2024-01-02 --end 2024-01-12 --sample-size 2 --seed 7
```
(Omit `--symbols` to sample from the stored repo universe on `--on-date`,
defaulting to `--end`. Requires network egress to yfinance and Stooq.)

Check local freshness with an explicit deadline:
```powershell
python -m yquant data freshness --symbols AAPL,MSFT --expected-date 2024-01-31 --deadline-utc 2024-02-01T00:45:00Z
```

Check local freshness using exchange close plus 45 minutes:
```powershell
python -m yquant data freshness --symbols AAPL,MSFT --expected-date 2024-01-31 --use-calendar-deadline
```

Load a survivorship-safe security master and query the point-in-time universe:
```powershell
python -m yquant data load-securities --csv securities.csv
python -m yquant data universe --on-date 2019-06-30 --market us
```

Update macro/index level series:
```powershell
python -m yquant data update-macro --series ^GSPC,^VIX --start 2024-01-01 --end 2024-01-31
```

Replay bars as known at a past instant (lookahead guard):
```powershell
python -m yquant data asof --symbols AAPL,MSFT --start 2024-01-01 --end 2024-01-31 --as-of-utc 2024-02-01T00:45:00Z
```

Inspect and run the unattended scheduler jobs:
```powershell
python -m yquant schedule list
python -m yquant schedule run-once --job freshness --on-date 2024-01-31
python -m yquant schedule run          # start the blocking daemon
```

## Test Coverage

Current M1 tests cover:
- yfinance/Stooq normalization.
- Raw vs adjusted read views.
- Manifest hash stability.
- Parquet round trip and upsert.
- Source fallback after fetch failure, empty result, and quality failure.
- Reconciliation mismatches and missing rows.
- Sampled live reconciliation: deterministic seeded sampling, both-source fetch,
  per-source fetch-failure recording, repo-universe sampling, and guard rails.
- Fresh, late, stale, and missing freshness states.
- Calendar-derived deadline logic with a fake exchange calendar.
- CLI parser coverage and execution-level reconciliation artifact output.
- Retry/backoff success, exhaustion, jitter bounds, and updater integration.
- Ledger bootstrap idempotency and risk_event/job_run round trips.
- Alert formatting and notifier transport (no network).
- Scheduler job skip/success/failure ledgering, alerting, and cron registration.
- Security master point-in-time universe (listed, delisted, boundary, fallback).
- Macro series canonicalization, dedup, yfinance normalization, and updater.
- As-of reads excluding future-recorded rows and staggered arrivals.
- Risk regime (trend/VIX), dynamic 2x gate, and ledgered proposal rejects.

Latest verification:
- `python -m pytest`: 174 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.
- CI (GitHub Actions) runs the same three checks on every push and PR.

## Remaining M1 Work

Next likely steps:
- Persist a bitemporal bar history so as-of replay can reconstruct overwritten
  earlier versions, not just exclude future-recorded rows.
- Wire a real security-master source (listing/delisting feed) behind an adapter;
  the current master is CSV-ingested.
- Compute the risk regime automatically from stored macro series inside the
  scheduler, rather than passing it in per call.
- Add persisted retry/backoff evidence and alert de-duplication for the daemon.
