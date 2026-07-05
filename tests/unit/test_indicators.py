import math

import pytest

from yquant.strategies.indicators import (
    annualized_vol,
    daily_returns,
    ewma_annualized_vol,
    moving_average,
    portfolio_returns,
    total_return,
)


def test_daily_returns() -> None:
    assert daily_returns([100.0, 110.0, 99.0]) == pytest.approx([0.1, -0.1])


def test_daily_returns_rejects_zero_price() -> None:
    with pytest.raises(ValueError, match="zero price"):
        daily_returns([0.0, 1.0])


def test_moving_average_uses_trailing_window() -> None:
    assert moving_average([1.0, 2.0, 3.0, 4.0], 2) == pytest.approx(3.5)


def test_moving_average_needs_enough_data() -> None:
    with pytest.raises(ValueError, match="at least"):
        moving_average([1.0], 2)


def test_total_return_with_skip_implements_12_1_momentum() -> None:
    # 14 prices; 12-1 momentum = return over 12 periods ending 1 before the last.
    prices = [float(p) for p in range(100, 114)]  # 100..113
    # end = len-1-skip = 13-1 = 12 → prices[12]=112; start = 12-12 = 0 → prices[0]=100
    assert total_return(prices, lookback=12, skip=1) == pytest.approx(112 / 100 - 1)


def test_total_return_insufficient_history() -> None:
    with pytest.raises(ValueError, match="at least"):
        total_return([1.0, 2.0], lookback=12, skip=1)


def test_annualized_vol_matches_manual() -> None:
    returns = [0.01, -0.01, 0.02, -0.02]
    manual_var = sum((r - sum(returns) / 4) ** 2 for r in returns) / 3
    expected = math.sqrt(manual_var) * math.sqrt(252)
    assert annualized_vol(returns) == pytest.approx(expected)


def test_annualized_vol_short_series_is_zero() -> None:
    assert annualized_vol([0.01]) == 0.0


def test_ewma_vol_weights_recent_more() -> None:
    calm_then_wild = [0.0, 0.0, 0.0, 0.05, -0.05, 0.05, -0.05]
    wild_then_calm = [0.05, -0.05, 0.05, -0.05, 0.0, 0.0, 0.0]
    assert ewma_annualized_vol(calm_then_wild) > ewma_annualized_vol(wild_then_calm)


def test_ewma_vol_rejects_bad_lambda() -> None:
    with pytest.raises(ValueError, match="lam"):
        ewma_annualized_vol([0.01, 0.02], lam=1.5)


def test_portfolio_returns_weighted() -> None:
    weights = {"A": 0.5, "B": 0.5}
    per_symbol = {"A": [0.02, 0.04], "B": [0.00, 0.00]}
    assert portfolio_returns(weights, per_symbol) == pytest.approx([0.01, 0.02])
