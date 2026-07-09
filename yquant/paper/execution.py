"""Execution-quality backfill: the digital twin's execution-error channel (08 §3).

The sim / twin marks assume a frictionless close-price fill (that is what keeps it
comparable to the backtest, so T7 parity holds). Reality does not: the plan models
a T+1 *open* fill at ``open × (1 ± slippage)`` clamped into ``[low, high]``. The
gap between the two is **execution error**, distinct from **hypothesis error**
(08 §3). This module replays a set of intended trades against the actual bar's
open/low/high and books the per-trade realised slippage, rolling it into a monthly
《执行质量报告》. Halt days fill nothing (T3'). Pure and deterministic — the "real"
side here is the frozen next-session bar, not a live wall clock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from yquant.backtest.costs import Instrument, Side, UsCostModel


@dataclass(frozen=True)
class IntendedTrade:
    """A proposal the twin assumed would fill at ``assumed_price`` (the close)."""

    day: date
    symbol: str
    side: Side
    shares: int
    assumed_price: float
    instrument: Instrument = "etf"


@dataclass(frozen=True)
class SessionBar:
    """The actual T+1 bar an intended trade executes against."""

    open: float
    low: float
    high: float
    is_halted: bool = False


@dataclass(frozen=True)
class RealizedFill:
    """One executed trade with its slippage vs the twin's assumed price."""

    day: date
    symbol: str
    side: Side
    shares: int
    assumed_price: float
    realized_price: float
    slippage_bps: float
    filled: bool
    reason: str  # "filled" | "halted"

    def as_dict(self) -> dict[str, object]:
        return {
            "day": self.day.isoformat(),
            "symbol": self.symbol,
            "side": self.side,
            "shares": self.shares,
            "assumed_price": round(self.assumed_price, 6),
            "realized_price": round(self.realized_price, 6),
            "slippage_bps": round(self.slippage_bps, 6),
            "filled": self.filled,
            "reason": self.reason,
        }


def realized_fill(
    trade: IntendedTrade,
    bar: SessionBar,
    *,
    model: UsCostModel | None = None,
) -> RealizedFill:
    """Fill one intended trade at ``open×(1±slippage)`` clamped to ``[low, high]``.

    A buy slips up, a sell slips down (adverse), by the instrument's slippage rate;
    the result is clamped into the session's traded range. Halt days do not fill.
    Slippage bps is measured *against the twin's assumed price*, signed so that a
    positive number always means worse-than-assumed execution.
    """

    if bar.is_halted:
        return RealizedFill(
            day=trade.day,
            symbol=trade.symbol,
            side=trade.side,
            shares=trade.shares,
            assumed_price=trade.assumed_price,
            realized_price=0.0,
            slippage_bps=0.0,
            filled=False,
            reason="halted",
        )

    cost_model = model or UsCostModel()
    rate = float(cost_model.slippage_rate_for(trade.instrument))
    direction = 1.0 if trade.side == "buy" else -1.0
    raw = bar.open * (1.0 + direction * rate)
    realized = min(max(raw, bar.low), bar.high)

    if trade.assumed_price > 0:
        signed = (realized - trade.assumed_price) / trade.assumed_price
        # A higher buy price / lower sell price is adverse; normalise to "worse = +".
        adverse = signed if trade.side == "buy" else -signed
        slippage_bps = adverse * 10_000.0
    else:
        slippage_bps = 0.0

    return RealizedFill(
        day=trade.day,
        symbol=trade.symbol,
        side=trade.side,
        shares=trade.shares,
        assumed_price=trade.assumed_price,
        realized_price=realized,
        slippage_bps=slippage_bps,
        filled=True,
        reason="filled",
    )


@dataclass(frozen=True)
class ExecutionQualityReport:
    """Monthly execution-quality summary (08 §3 《执行质量报告》)."""

    fills: list[RealizedFill]
    filled_count: int
    halted_count: int
    mean_slippage_bps: float
    worst_slippage_bps: float
    total_slippage_usd: float

    def as_dict(self) -> dict[str, object]:
        return {
            "fills": [f.as_dict() for f in self.fills],
            "filled_count": self.filled_count,
            "halted_count": self.halted_count,
            "mean_slippage_bps": round(self.mean_slippage_bps, 6),
            "worst_slippage_bps": round(self.worst_slippage_bps, 6),
            "total_slippage_usd": round(self.total_slippage_usd, 6),
        }


def backfill_execution_quality(
    trades: Sequence[IntendedTrade],
    bars: Mapping[tuple[date, str], SessionBar],
) -> ExecutionQualityReport:
    """Book realised slippage for each intended trade against its actual bar.

    ``bars`` maps ``(day, symbol)`` to the T+1 bar the trade fills against; a
    trade with no matching bar is treated as halted (nothing to fill against).
    """

    realized: list[RealizedFill] = []
    for trade in trades:
        bar = bars.get((trade.day, trade.symbol))
        if bar is None:
            bar = SessionBar(open=0.0, low=0.0, high=0.0, is_halted=True)
        realized.append(realized_fill(trade, bar))

    filled = [f for f in realized if f.filled]
    halted = [f for f in realized if not f.filled]
    slippages = [f.slippage_bps for f in filled]
    mean_bps = sum(slippages) / len(slippages) if slippages else 0.0
    worst_bps = max(slippages) if slippages else 0.0
    total_usd = sum(
        abs(f.realized_price - f.assumed_price) * f.shares for f in filled
    )
    return ExecutionQualityReport(
        fills=realized,
        filled_count=len(filled),
        halted_count=len(halted),
        mean_slippage_bps=mean_bps,
        worst_slippage_bps=worst_bps,
        total_slippage_usd=total_usd,
    )


__all__ = [
    "ExecutionQualityReport",
    "IntendedTrade",
    "RealizedFill",
    "SessionBar",
    "backfill_execution_quality",
    "realized_fill",
]
