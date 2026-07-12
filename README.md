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

## Quick Start

Python 3.11 is the reference runtime.

```powershell
poetry install --with dev,datasource
poetry run yquant doctor
poetry run yquant data update --symbols AAPL,MSFT,SPY --start 2024-01-02 --end 2024-01-12
poetry run yquant data freshness --symbols AAPL,MSFT,SPY --expected-date 2024-01-12
poetry run yquant backtest --symbols SPY --start 2024-01-02 --end 2024-01-12
```

Runtime data, SQLite ledgers, quality artifacts, and logs are written below
`data/` by the example configuration and are ignored by Git.

## Alpha Verification

The release gate is:

```powershell
poetry run ruff check .
poetry run mypy yquant tests
poetry run pytest --cov=yquant --cov-report=term-missing --cov-fail-under=90
poetry run python scripts/mutation_check.py
poetry run python scripts/chaos_drill.py
```

See `research/RELEASE_V0_1_ALPHA.md` for the release boundary, verification
evidence, known limitations, and the promotion gate for v0.1.
