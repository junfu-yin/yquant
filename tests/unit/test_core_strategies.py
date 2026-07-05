from datetime import date

import pytest

from yquant.strategies.core import (
    dual_momentum_weights,
    is_above_trend,
    trend_status,
)


def _rising(base: float, step: float, n: int = 14) -> list[float]:
    return [base + step * i for i in range(n)]


def test_dual_momentum_selects_top_3_equal_weight() -> None:
    # Four risky sleeves with clearly different slopes + a flat cash proxy.
    monthly = {
        "SPY": _rising(100, 5),  # strongest
        "EFA": _rising(100, 4),
        "EEM": _rising(100, 3),
        "TLT": _rising(100, 1),  # weakest risky → excluded from top 3
        "BIL": [100.0] * 14,  # cash proxy, flat
    }
    portfolio = dual_momentum_weights(monthly, date(2024, 6, 3))

    assert set(portfolio.weights) == {"SPY", "EFA", "EEM"}
    assert all(w == pytest.approx(1 / 3) for w in portfolio.weights.values())
    assert all(layer == "core" for layer in portfolio.layers.values())
    assert portfolio.cash_weight == pytest.approx(0.0)


def test_dual_momentum_absolute_filter_sends_weak_sleeve_to_cash() -> None:
    # All risky sleeves fall over 12 months; cash proxy rises → all filtered out.
    monthly = {
        "SPY": list(reversed(_rising(100, 5))),
        "EFA": list(reversed(_rising(100, 4))),
        "EEM": list(reversed(_rising(100, 3))),
        "TLT": list(reversed(_rising(100, 2))),
        "BIL": _rising(100, 1),  # cash proxy rising → beats every falling sleeve
    }
    portfolio = dual_momentum_weights(monthly, date(2024, 6, 3))

    assert portfolio.weights == {}
    assert portfolio.cash_weight == pytest.approx(1.0)


def test_dual_momentum_respects_budget() -> None:
    monthly = {
        "SPY": _rising(100, 5),
        "EFA": _rising(100, 4),
        "EEM": _rising(100, 3),
        "TLT": _rising(100, 1),
        "BIL": [100.0] * 14,
    }
    portfolio = dual_momentum_weights(monthly, date(2024, 6, 3), budget=0.8)

    assert portfolio.invested_weight() == pytest.approx(0.8)
    assert all(w == pytest.approx(0.8 / 3) for w in portfolio.weights.values())


def test_dual_momentum_requires_cash_proxy() -> None:
    with pytest.raises(ValueError, match="cash proxy"):
        dual_momentum_weights({"SPY": _rising(100, 5)}, date(2024, 6, 3))


def test_trend_gate_above_and_below() -> None:
    rising = _rising(100, 5, n=12)
    assert is_above_trend(rising, window=10) is True

    falling = list(reversed(rising))
    assert is_above_trend(falling, window=10) is False


def test_trend_status_maps_symbols() -> None:
    monthly = {
        "SPY": _rising(100, 5, n=12),
        "EEM": list(reversed(_rising(100, 5, n=12))),
        "SHORT": [100.0] * 4,  # too short → skipped
    }
    status = trend_status(monthly, window=10)

    assert status == {"SPY": True, "EEM": False}
