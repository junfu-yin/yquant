# v0.1.0-alpha.1 Release Record

Status: release candidate; all automated/runtime gates and final Git review are
green. Publication remains.

## Contract

This is a private, single-user, shadow-only engineering alpha. It provides a
reproducible data, research, risk-rule, QA, and ledger foundation. It never
places an order. The owner remains the sole execution authority through
Selfwealth.

The executable trading surface is intentionally disabled as a release claim:

- proposals are observations, not instructions;
- 2x/3x/inverse ETF and meme-stock paths remain research/demo only;
- LLM components may summarize or be evaluated but do not size positions;
- the scheduled M9 job is not a trusted decision input until real pillar
  derivation replaces its all-stale default;
- backtest performance is research-only until T-close proposal to T+1-open
  execution is implemented and independently reconciled;
- synthetic golden windows and drills prove determinism/process plumbing, not
  historical performance or crisis timing.

## Release-Blocking Fixes

- Cost tiers now receive separate target-provider instances. Stateful signal
  consumption can no longer leave the 1x strategy report silently all-cash.
- Trade proposal share counts use the target-minus-current weight delta. Full
  exits, partial reductions, partial additions, and new positions are covered.
- Report construction rejects a provider factory that returns the same instance
  more than once.
- Every report carries the alpha same-session-close execution warning.
- Nasdaq is the default independent daily-bar backup/reconciliation source.
  `pandas-datareader` 0.11 removed its Stooq securities reader, so retaining
  Stooq as the alpha default would make the declared live quality gate
  impossible in a clean install; the legacy adapter remains available.

## Verification Gate

- [x] Ruff passes for the full repository.
- [x] Mypy passes for `yquant` and `tests`.
- [x] Full pytest suite passes.
- [x] Coverage is at least 90%.
- [x] Curated mutation check kills every mutant.
- [x] Chaos drill handles every injected scenario.
- [x] Package metadata and lock file are valid.
- [x] CLI doctor reports alpha / shadow-only.
- [x] Fixed-window live data update succeeds against a real source.
- [x] Fixed-window live dual-source reconciliation leaves an auditable result.
- [x] Backtest CLI over fetched data produces fills in all three cost tiers.
- [x] Git worktree contains only reviewed release changes.

Verification snapshot (2026-07-12):

- Ruff: pass.
- Mypy: pass, 182 source files.
- Pytest: 603 passed; total coverage 94.97%.
- Mutation check: 12/12 killed, including both release-blocking regressions.
- Chaos drill: 4/4 scenarios handled and ledgered/alerted.
- Poetry: lock check passed; `yquant-0.1.0a1-py3-none-any.whl` built and
  installed into an isolated venv; installed CLI reported `0.1.0a1`.
- Live primary update: AAPL/MSFT/SPY, 2026-06-29 through 2026-07-10, 9 rows
  each from yfinance with manifest and quality artifact.
- Live P3 sample (seed 7): yfinance versus Nasdaq for AAPL/MSFT, 18 compared
  rows, zero fetch failures, zero missing rows, zero mismatches, consistency
  1.000000.
- Live-data SPY backtest: all 0x/1x/2x tiers executed one fill; the report
  displayed the alpha same-session-close warning.

Ignored runtime evidence is under `data/alpha-smoke/`. Final commands and
results are also recorded in `research/IMPLEMENTATION_LOG.md` before tagging.

## Promotion to v0.1

Promotion is evidence-driven, not automatic after a date. The minimum is 20 US
trading sessions of real shadow operation with no unresolved P0/P1 issue, no
silent stale-data success, complete ledger/replay evidence, correct T+1-open
execution semantics, real M9 pillar inputs, and a successful backup/restore
drill.
