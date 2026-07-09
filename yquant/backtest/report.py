"""M2 backtest report (03 §5.2 mandatory fields).

Every strategy report must carry: a SPY buy-and-hold benchmark, a 0/1x/2x cost
sensitivity table, walk-forward out-of-sample and parameter-sensitivity slots,
warnings, and the rejection ledger. Walk-forward and parameter sweeps are driven
by the caller (they need multiple providers / parameter sets), so this module
exposes seams for them rather than inventing splits here.

The report is a pure function of the backtest inputs and is fully JSON-safe so
the ledger and UI can persist it verbatim (07 replay).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

import pandas as pd

from yquant.backtest.costs import Instrument, UsCostModel
from yquant.backtest.engine import BacktestResult, TargetProvider, run_backtest
from yquant.strategies.base import TargetPortfolio

_DAYS_PER_YEAR = 365.25
_COST_TIERS: tuple[tuple[str, str], ...] = (
    ("0x", "0"),
    ("1x", "1"),
    ("2x", "2"),
)


@dataclass(frozen=True)
class PerformanceMetrics:
    """Headline metrics for one equity curve, all JSON-safe."""

    start: date | None
    end: date | None
    initial_equity: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    num_fills: int
    gfv_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "initial_equity": round(self.initial_equity, 6),
            "final_equity": round(self.final_equity, 6),
            "total_return": round(self.total_return, 6),
            "annualized_return": round(self.annualized_return, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "num_fills": self.num_fills,
            "gfv_count": self.gfv_count,
        }


def annualized_return(result: BacktestResult) -> float:
    """CAGR from the first to last equity point; falls back to total return."""

    curve = result.equity_curve
    if len(curve) < 2 or result.initial_cash <= 0:
        return result.total_return()
    span_days = (curve[-1].day - curve[0].day).days
    if span_days <= 0:
        return result.total_return()
    years = span_days / _DAYS_PER_YEAR
    growth = result.final_equity() / result.initial_cash
    if growth <= 0:
        return -1.0
    return float(growth ** (1.0 / years)) - 1.0


def metrics_of(result: BacktestResult) -> PerformanceMetrics:
    curve = result.equity_curve
    return PerformanceMetrics(
        start=curve[0].day if curve else None,
        end=curve[-1].day if curve else None,
        initial_equity=result.initial_cash,
        final_equity=result.final_equity(),
        total_return=result.total_return(),
        annualized_return=annualized_return(result),
        max_drawdown=result.max_drawdown(),
        num_fills=len(result.fills),
        gfv_count=result.gfv_count,
    )


def scale_cost_model(model: UsCostModel, multiplier: Decimal) -> UsCostModel:
    """Scale every cost component (0/1x/2x sensitivity tiers)."""

    return replace(
        model,
        commission_per_trade=model.commission_per_trade * multiplier,
        sec_fee_rate=model.sec_fee_rate * multiplier,
        finra_taf_per_share=model.finra_taf_per_share * multiplier,
        finra_taf_cap=model.finra_taf_cap * multiplier,
        slippage_rate_etf=model.slippage_rate_etf * multiplier,
        slippage_rate_single=model.slippage_rate_single * multiplier,
    )


def _buy_and_hold_provider(symbol: str) -> TargetProvider:
    """Full-weight target on the first session it can price ``symbol``."""

    placed = {"done": False}

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if placed["done"]:
            return None
        price = closes.get(symbol)
        if price is None or price <= 0:
            return None
        placed["done"] = True
        return TargetPortfolio(
            as_of=day,
            weights={symbol: 1.0},
            layers={symbol: "core"},
            cash_weight=0.0,
        )

    return provider


def build_report(
    *,
    bars: pd.DataFrame,
    target_provider: TargetProvider,
    initial_cash: float,
    cost_model: UsCostModel | None = None,
    instruments: Mapping[str, Instrument] | None = None,
    min_weight_change: float = 0.0,
    benchmark_symbol: str = "SPY",
    walk_forward: object | None = None,
    parameter_sensitivity: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Run the strategy at 0/1x/2x cost, plus a SPY benchmark, and report.

    Returns a JSON-safe dict with the mandatory M2 report fields. Walk-forward
    and parameter sensitivity are computed by the caller (they need multiple
    providers / parameter sets) and passed in; when omitted the slots stay empty.
    """

    base_model = cost_model or UsCostModel()
    instruments = instruments or {}
    warnings: list[str] = []

    cost_tiers: list[dict[str, object]] = []
    strategy_result_1x: BacktestResult | None = None
    for label, factor in _COST_TIERS:
        model = scale_cost_model(base_model, Decimal(factor))
        result = run_backtest(
            bars=bars,
            target_provider=target_provider,
            initial_cash=initial_cash,
            cost_model=model,
            instruments=instruments,
            min_weight_change=min_weight_change,
        )
        cost_tiers.append({"tier": label, "metrics": metrics_of(result).as_dict()})
        if label == "1x":
            strategy_result_1x = result
            warnings.extend(result.warnings)

    assert strategy_result_1x is not None  # 1x tier always runs.

    benchmark = _run_benchmark(
        bars=bars,
        initial_cash=initial_cash,
        cost_model=base_model,
        instruments=instruments,
        benchmark_symbol=benchmark_symbol,
        warnings=warnings,
    )

    return {
        "strategy": {
            "metrics": metrics_of(strategy_result_1x).as_dict(),
            "digest": strategy_result_1x.digest(),
            "final_positions": strategy_result_1x.final_positions,
        },
        "benchmark": benchmark,
        "cost_sensitivity": cost_tiers,
        "walk_forward": walk_forward if walk_forward is not None else [],
        "parameter_sensitivity": parameter_sensitivity if parameter_sensitivity is not None else [],
        "warnings": _dedupe(warnings),
        "rejections": [
            {
                "day": r.day.isoformat(),
                "symbol": r.symbol,
                "side": r.side,
                "shares": r.shares,
                "reason": r.reason,
            }
            for r in strategy_result_1x.rejections
        ],
    }


def _run_benchmark(
    *,
    bars: pd.DataFrame,
    initial_cash: float,
    cost_model: UsCostModel,
    instruments: Mapping[str, Instrument],
    benchmark_symbol: str,
    warnings: list[str],
) -> dict[str, object] | None:
    if benchmark_symbol not in set(bars["symbol"].astype(str)):
        warnings.append(f"benchmark {benchmark_symbol} not in bars; comparison skipped")
        return None
    result = run_backtest(
        bars=bars,
        target_provider=_buy_and_hold_provider(benchmark_symbol),
        initial_cash=initial_cash,
        cost_model=cost_model,
        instruments=instruments,
    )
    return {"symbol": benchmark_symbol, "metrics": metrics_of(result).as_dict()}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
