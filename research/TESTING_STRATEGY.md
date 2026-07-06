# Testing & Quality Strategy

Status: implementation-side note, not authoritative product docs (`docs/`
untouched).

Date: 2026-07-06

This describes the layered test suite and the automated quality gates that guard
the product. The goal is not a coverage number but *behavioural confidence*: the
system must reliably say "no" to bad data and bad requests.

## Layers

1. **Unit tests** — pure logic and small collaborators, hermetic (no network,
   no clock dependence). The bulk of the suite.
2. **Contract tests** — the network-facing normalizers (yfinance/Stooq adapters,
   macro adapter, EDGAR/probe helpers) exercised against realistic *and*
   malformed payloads via injected fake modules, so parsing is covered without
   egress.
3. **Property-based tests** (Hypothesis, `tests/unit/test_property_invariants.py`)
   — invariants over generated inputs: sampling determinism/order-independence,
   retry backoff monotonicity and cap, canonicalization idempotence,
   reconciliation symmetry, and point-in-time universe correctness.
4. **Integration / end-to-end** (`tests/unit/test_cli_e2e.py`) — drive
   `main(argv)` for every CLI subcommand against a temp config and repo; network
   subcommands use monkeypatched source factories.
5. **Traps** (`tests/traps/`) — adversarial assertions that the defensive
   guarantees hold: risk mechanisms (T14/T15) and data integrity (T16–T20:
   OHLC rejection, no-future-data, survivorship, deterministic upsert,
   adjustment factor).

## Automated gates (CI)

Every push and PR runs, via `.github/workflows/ci.yml`:

- `ruff check .` — lint.
- `mypy yquant tests` — static types (strict-ish: `disallow_untyped_defs`).
- `pytest --cov=yquant --cov-fail-under=90` — tests plus a coverage floor that
  fails the build below 90% (ratcheted up as coverage grew: 80 → 88 → 90).
- `python scripts/mutation_check.py` — mutation check on core logic.

## Mutation testing

`scripts/mutation_check.py` is a small, deterministic harness (no external
dependency; mutmut's environment model was too awkward here). For each curated
mutation of `retry.py`, `regime.py`, and `reconcile.py` it patches the source,
runs the targeted tests, and requires them to **fail** — a surviving mutant
means the tests do not actually pin that behaviour. It clears `__pycache__` and
runs subprocesses with `PYTHONDONTWRITEBYTECODE=1` so same-second rewrites cannot
load stale bytecode and skew results. Current status: 7/7 mutants killed.

To extend: add a `Mutation(...)` entry (module, targeted tests, old→new source,
label). Prefer mutations that represent plausible bugs (boundary/operator/const).

## Coverage snapshot

- Total: ~91% (network entrypoints `__main__`/`ui` omitted from the measured
  surface; probes/adapters covered via mocked modules).
- Strong: risk, discipline, ledger, reconcile, repo, security master, macro,
  scheduler jobs.

## Deliberately out of scope for CI

- **Real live egress** (yfinance/Stooq/EDGAR, real Feishu delivery) — blocked by
  the sandbox network policy and inherently flaky. Run the live CLI paths
  (`data update`, `data reconcile-live`, `data update-macro`) manually where
  egress is open; the normalization logic they exercise is contract-tested.

## How to run locally

```bash
poetry run ruff check .
poetry run mypy yquant tests
poetry run pytest --cov=yquant --cov-report=term-missing --cov-fail-under=90
poetry run python scripts/mutation_check.py
```
