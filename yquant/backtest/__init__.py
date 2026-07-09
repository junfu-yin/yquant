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
from yquant.backtest.walkforward import (
    WalkForwardWindow,
    parameter_sensitivity,
    rolling_windows,
    run_walk_forward,
    stitch_oos_metrics,
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
    "WalkForwardWindow",
    "annualized_return",
    "build_report",
    "metrics_of",
    "parameter_sensitivity",
    "rolling_windows",
    "run_backtest",
    "run_walk_forward",
    "scale_cost_model",
    "stitch_oos_metrics",
    "trade_cost",
    "us_trade_cost",
]
