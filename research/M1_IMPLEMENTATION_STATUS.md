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
- Local freshness checks.
- JSON quality artifacts under `data/quality` by default.

## Operator Commands

Manual daily-bar update:
```powershell
python -m yquant data update --symbols AAPL,MSFT,SPY --start 2024-01-01 --end 2024-01-31
```

Compare persisted yfinance vs Stooq rows:
```powershell
python -m yquant data reconcile --symbols AAPL,MSFT --start 2024-01-01 --end 2024-01-31
```

Check local freshness with an explicit deadline:
```powershell
python -m yquant data freshness --symbols AAPL,MSFT --expected-date 2024-01-31 --deadline-utc 2024-02-01T00:45:00Z
```

Check local freshness using exchange close plus 45 minutes:
```powershell
python -m yquant data freshness --symbols AAPL,MSFT --expected-date 2024-01-31 --use-calendar-deadline
```

## Test Coverage

Current M1 tests cover:
- yfinance/Stooq normalization.
- Raw vs adjusted read views.
- Manifest hash stability.
- Parquet round trip and upsert.
- Source fallback after fetch failure, empty result, and quality failure.
- Reconciliation mismatches and missing rows.
- Fresh, late, stale, and missing freshness states.
- Calendar-derived deadline logic with a fake exchange calendar.
- CLI parser coverage and execution-level reconciliation artifact output.

Latest verification:
- `python -m pytest`: 115 passed.
- `python -m ruff check .`: passed.
- `python -m mypy yquant tests`: passed.

## Remaining M1 Work

Next likely steps:
- Add a sampled live dual-source reconciliation job for P3 evidence.
- Add scheduler integration after the manual commands stay stable.
- Add retry/backoff policy before scheduler activation.
- Add macro/index storage schemas and update commands.
- Add point-in-time universe handling; current universe is only bar-presence
  based and not survivorship-safe for individual-stock universe strategies.
