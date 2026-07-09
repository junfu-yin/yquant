"""Backtest engine modules (M2, 03 §5.2)."""

from yquant.backtest.costs import (
    CostBreakdown,
    Instrument,
    Side,
    UsCostModel,
    trade_cost,
    us_trade_cost,
)
from yquant.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    EquityPoint,
    Fill,
    Order,
    Rejection,
    TargetProvider,
    run_backtest,
)
from yquant.backtest.report import (
    PerformanceMetrics,
    annualized_return,
    build_report,
    metrics_of,
    scale_cost_model,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "CostBreakdown",
    "EquityPoint",
    "Fill",
    "Instrument",
    "Order",
    "PerformanceMetrics",
    "Rejection",
    "Side",
    "TargetProvider",
    "UsCostModel",
    "annualized_return",
    "build_report",
    "metrics_of",
    "run_backtest",
    "scale_cost_model",
    "trade_cost",
    "us_trade_cost",
]
