"""Property-based invariants for the M2 backtest engine (06 §3).

Over generated price paths and target weights the engine must never violate the
accounting and constraint invariants: cash conservation, non-negative holdings,
non-negative fees carrying the fixed commission, fill prices inside the day's
[low, high], and a layer-budget sum that never exceeds 100% (no leverage). These
are the double-Broker invariants the plan requires; they run against the pure
backtest path here and against the PaperBroker in WP9.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from yquant.backtest.engine import run_backtest
from yquant.qa.metrics import (
    check_p1_accounting_conservation,
)
from yquant.strategies.base import TargetPortfolio

_SYMBOLS = ("SPY", "TLT", "GLD")
_PRICE = st.floats(min_value=5.0, max_value=800.0, allow_nan=False, allow_infinity=False)
_WEIGHT = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


def _bars(paths: dict[str, list[float]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2024, 1, 2)
    for symbol, closes in paths.items():
        for offset, close in enumerate(closes):
            day = start + timedelta(days=offset)
            price = round(close, 4)
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "low": round(price * 0.98, 4),
                    "high": round(price * 1.02, 4),
                    "close": price,
                    "is_halted": False,
                }
            )
    return pd.DataFrame(rows)


def _normalize(raw: dict[str, float]) -> dict[str, float]:
    """Scale weights so their sum never exceeds 1 (long-only, no leverage)."""

    total = sum(raw.values())
    if total <= 1.0:
        return {s: w for s, w in raw.items() if w > 0}
    return {s: w / total for s, w in raw.items() if w > 0}


@settings(max_examples=120, deadline=None)
@given(
    weights=st.fixed_dictionaries({s: _WEIGHT for s in _SYMBOLS}),
    path_len=st.integers(min_value=3, max_value=8),
    seed_prices=st.lists(_PRICE, min_size=3, max_size=8),
)
def test_engine_preserves_core_invariants(
    weights: dict[str, float], path_len: int, seed_prices: list[float]
) -> None:
    closes = (seed_prices * path_len)[:path_len]
    paths = {s: closes for s in _SYMBOLS}
    bars = _bars(paths)
    target = _normalize(weights)

    def provider(day: date, prices: Mapping[str, float]) -> TargetPortfolio | None:
        if day != bars["date"].min():
            return None
        return TargetPortfolio(
            as_of=day,
            weights=dict(target),
            layers=dict.fromkeys(target, "core"),
            cash_weight=max(0.0, 1.0 - sum(target.values())),
        )

    result = run_backtest(bars=bars, target_provider=provider, initial_cash=50_000.0)

    # Holdings never go negative (long-only, no shorting).
    assert all(shares >= 0 for shares in result.final_positions.values())
    # Fees are non-negative and every fill carries the fixed commission.
    for fill in result.fills:
        assert fill.commission >= 0.0
        assert fill.slippage >= 0.0
        assert fill.regulatory_fees >= 0.0
        assert fill.cost_total >= fill.commission
    # Fill prices are the session close, which lies inside the day's [low, high].
    price_index = {
        (row.symbol, row.date): (row.low, row.high)
        for row in bars.itertuples(index=False)
    }
    for fill in result.fills:
        low, high = price_index[(fill.symbol, fill.day)]
        assert low <= fill.price <= high
    # Cash conservation (P1) holds to the cent.
    assert check_p1_accounting_conservation(result).passed


@settings(max_examples=80, deadline=None)
@given(weights=st.fixed_dictionaries({s: _WEIGHT for s in _SYMBOLS}))
def test_normalized_target_never_leverages(weights: dict[str, float]) -> None:
    target = _normalize(weights)
    portfolio = TargetPortfolio(
        as_of=date(2024, 1, 2),
        weights=dict(target),
        layers=dict.fromkeys(target, "core"),
        cash_weight=max(0.0, 1.0 - sum(target.values())),
    )
    # Invested + cash weight never exceeds 1 (the no-leverage validator).
    assert portfolio.invested_weight() + portfolio.cash_weight <= 1.0 + 1e-9
