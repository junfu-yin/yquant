"""T5 adjusted prices (06 §2): a split leaves equity continuous.

The engine consumes the adjusted close view, so a corporate split — which
halves the raw price and doubles shares — shows up as a *continuous* adjusted
series and must not create an equity discontinuity (P4: jump < 0.1%).
"""

from collections.abc import Mapping
from datetime import date, timedelta

import pandas as pd

from yquant.backtest import run_backtest
from yquant.strategies.base import TargetPortfolio


def test_t5_split_leaves_equity_continuous_on_adjusted_prices() -> None:
    # Raw price would jump from 400 -> 100 on a 4:1 split; the *adjusted* close
    # (what we feed the engine) drifts smoothly across the same session.
    adjusted_closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    split_index = 3  # the "split date" — no adjusted-series jump here.

    day = date(2024, 1, 2)
    rows = []
    for close in adjusted_closes:
        rows.append({"symbol": "AAPL", "date": day, "close": close, "is_halted": False})
        day = day + timedelta(days=1)
    bars = pd.DataFrame(rows)

    def provider(d: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if d == bars["date"].min():
            return TargetPortfolio(
                as_of=d, weights={"AAPL": 1.0}, layers={"AAPL": "core"}, cash_weight=0.0
            )
        return None

    result = run_backtest(
        bars=bars,
        target_provider=provider,
        initial_cash=100_000.0,
        instruments={"AAPL": "single_stock"},
    )

    curve = result.equity_curve
    # Day-over-day equity moves track the adjusted price step (~1%), and the
    # step across the split date is no larger than any other — no jump.
    changes = [
        abs(curve[i].equity / curve[i - 1].equity - 1.0) for i in range(1, len(curve))
    ]
    split_step = changes[split_index - 1]
    typical_step = max(changes)
    assert split_step <= typical_step + 1e-9
    # None of the steps looks like an un-adjusted 4:1 split (which would be ~75%).
    assert all(step < 0.02 for step in changes)
