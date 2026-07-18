"""M2 deterministic backtest engine (03 §5.2).

A pure-Python, replayable event loop that consumes the same
:class:`~yquant.strategies.base.TargetPortfolio` the live path produces and
turns it into fills under the US constraint layer:

* halt/halted days reject orders with zero fill (T3');
* whole-share lots (US fractional shares are out of scope for v3.1a);
* no same-day sell ban — a position may be sold the session it was bought (T6);
* fills execute at the (adjusted) close, so splits leave equity continuous (T5);
* cash-account settlement: sell proceeds are unsettled for ``T+N`` sessions and
  buying with unsettled funds is flagged as a Good-Faith Violation (T6).

No randomness and no wall-clock reads, so a run is a pure function of its inputs
and :meth:`BacktestResult.digest` reproduces bit-for-bit across runs (07 replay).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from yquant.backtest.costs import CostBreakdown, Instrument, Side, UsCostModel, us_trade_cost
from yquant.datasrc.market_rules import market_rules
from yquant.strategies.base import TargetPortfolio

# A rebalance signal source: given the session date and that day's close prices,
# return a desired TargetPortfolio, or None to hold the current book unchanged.
TargetProvider = Callable[[date, Mapping[str, float]], TargetPortfolio | None]

_EPS = 1e-9


@dataclass(frozen=True)
class Order:
    """A single whole-share order submitted to the engine."""

    symbol: str
    side: Side
    shares: int
    instrument: Instrument = "etf"


@dataclass(frozen=True)
class Fill:
    """An executed order with its itemised costs (all USD)."""

    day: date
    symbol: str
    side: Side
    shares: int
    price: float
    commission: float
    slippage: float
    regulatory_fees: float
    slippage_bps: float
    used_unsettled_funds: bool

    @property
    def gross(self) -> float:
        return self.shares * self.price

    @property
    def cost_total(self) -> float:
        return self.commission + self.slippage + self.regulatory_fees


@dataclass(frozen=True)
class Rejection:
    """An order that could not fill, kept for the report's rejection ledger."""

    day: date
    symbol: str
    side: Side
    shares: int
    reason: str  # halted | insufficient_funds | no_position | non_positive


@dataclass
class _Settlement:
    """Unsettled sell proceeds maturing on ``settle_date`` (None = beyond window)."""

    settle_date: date | None
    amount: float


@dataclass(frozen=True)
class EquityPoint:
    day: date
    equity: float


@dataclass(frozen=True)
class BacktestResult:
    """Everything a report needs, all JSON-safe for the ledger/UI."""

    equity_curve: list[EquityPoint]
    fills: list[Fill]
    rejections: list[Rejection]
    gfv_count: int
    final_positions: dict[str, int]
    final_cash: float
    initial_cash: float
    warnings: list[str]

    def final_equity(self) -> float:
        return self.equity_curve[-1].equity if self.equity_curve else self.initial_cash

    def total_return(self) -> float:
        if self.initial_cash <= 0:
            return 0.0
        return self.final_equity() / self.initial_cash - 1.0

    def max_drawdown(self) -> float:
        """Largest peak-to-trough decline of the equity curve (>= 0)."""

        peak = float("-inf")
        worst = 0.0
        for point in self.equity_curve:
            peak = max(peak, point.equity)
            if peak > 0:
                worst = max(worst, (peak - point.equity) / peak)
        return worst

    def digest(self) -> str:
        """Stable SHA-256 over the rounded curve and fills (replay determinism)."""

        payload = {
            "equity_curve": [[p.day.isoformat(), round(p.equity, 6)] for p in self.equity_curve],
            "fills": [
                [
                    f.day.isoformat(),
                    f.symbol,
                    f.side,
                    f.shares,
                    round(f.price, 6),
                    round(f.cost_total, 6),
                ]
                for f in self.fills
            ],
            "gfv_count": self.gfv_count,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BacktestEngine:
    """Mutable account state driven one order at a time.

    Callers usually go through :func:`run_backtest`, but the order primitive is
    public so tests can exercise same-day round trips and settlement directly.
    """

    def __init__(
        self,
        *,
        initial_cash: float,
        trading_dates: Sequence[date],
        cost_model: UsCostModel | None = None,
    ) -> None:
        if not math.isfinite(initial_cash) or initial_cash < 0:
            raise ValueError("initial_cash must be finite and non-negative")
        if len(set(trading_dates)) != len(trading_dates):
            raise ValueError("trading_dates must not contain duplicates")
        if trading_dates != sorted(trading_dates):
            raise ValueError("trading_dates must be sorted in ascending order")
        self.settled_cash = float(initial_cash)
        self.positions: dict[str, int] = {}
        self.gfv_count = 0
        self.fills: list[Fill] = []
        self.rejections: list[Rejection] = []
        self._unsettled: list[_Settlement] = []
        self._model = cost_model or UsCostModel()
        self._dates: list[date] = list(trading_dates)
        self._index: dict[date, int] = {
            trading_day: index for index, trading_day in enumerate(self._dates)
        }

    def unsettled_total(self) -> float:
        return sum(item.amount for item in self._unsettled)

    def buying_power(self) -> float:
        """Cash a cash-account can deploy today: settled plus unsettled proceeds."""

        return self.settled_cash + self.unsettled_total()

    def settle_due(self, day: date) -> None:
        """Move proceeds whose settlement date has arrived into settled cash."""

        remaining: list[_Settlement] = []
        for item in self._unsettled:
            if item.settle_date is not None and item.settle_date <= day:
                self.settled_cash += item.amount
            else:
                remaining.append(item)
        self._unsettled = remaining

    def equity(self, prices: Mapping[str, float]) -> float:
        """Total account equity: settled + unsettled cash + marked positions."""

        market_value = sum(
            shares * prices.get(symbol, 0.0) for symbol, shares in self.positions.items()
        )
        return self.settled_cash + self.unsettled_total() + market_value

    def submit_order(
        self,
        order: Order,
        *,
        day: date,
        price: float,
        is_halted: bool,
    ) -> Fill | Rejection:
        """Execute one order under the US constraint layer; never raises on rules."""

        if is_halted:
            return self._reject(order, day, "halted")
        if order.side not in ("buy", "sell"):
            return self._reject(order, day, "invalid_side")
        if order.instrument not in ("etf", "single_stock"):
            return self._reject(order, day, "invalid_instrument")
        if order.shares <= 0 or not math.isfinite(price) or price <= 0:
            return self._reject(order, day, "non_positive")
        if order.side == "buy":
            return self._buy(order, day, price)
        return self._sell(order, day, price)

    def _buy(self, order: Order, day: date, price: float) -> Fill | Rejection:
        slip = float(self._model.slippage_rate_for(order.instrument))
        commission = float(self._model.commission_per_trade)
        budget = self.buying_power()
        # Largest whole-share lot whose notional + commission + slippage fits the
        # available buying power. Solves s*price*(1+slip) + commission <= budget.
        headroom = budget - commission
        if headroom <= 0:
            return self._reject(order, day, "insufficient_funds")
        affordable = math.floor(headroom / (price * (1.0 + slip)))
        shares = min(order.shares, affordable)
        if shares <= 0:
            return self._reject(order, day, "insufficient_funds")

        cost = us_trade_cost(
            "buy", Decimal(shares), Decimal(str(price)), self._model, instrument=order.instrument
        )
        gross = shares * price
        total_needed = gross + float(cost.total)
        used_unsettled = total_needed > self.settled_cash + _EPS
        if used_unsettled:
            self.gfv_count += 1
        self.settled_cash -= total_needed
        self.positions[order.symbol] = self.positions.get(order.symbol, 0) + shares
        return self._record_fill(order, day, shares, price, cost, gross, used_unsettled)

    def _sell(self, order: Order, day: date, price: float) -> Fill | Rejection:
        held = self.positions.get(order.symbol, 0)
        shares = min(order.shares, held)
        if shares <= 0:
            return self._reject(order, day, "no_position")

        cost = us_trade_cost(
            "sell", Decimal(shares), Decimal(str(price)), self._model, instrument=order.instrument
        )
        gross = shares * price
        proceeds = gross - float(cost.total)
        settlement_days = market_rules(order.symbol, "us", day).settlement_days
        self._unsettled.append(_Settlement(self._settle_date(day, settlement_days), proceeds))
        remaining = held - shares
        if remaining:
            self.positions[order.symbol] = remaining
        else:
            self.positions.pop(order.symbol, None)
        return self._record_fill(order, day, shares, price, cost, gross, used_unsettled=False)

    def _record_fill(
        self,
        order: Order,
        day: date,
        shares: int,
        price: float,
        cost: CostBreakdown,
        gross: float,
        used_unsettled: bool,
    ) -> Fill:
        slippage = float(cost.slippage)
        fill = Fill(
            day=day,
            symbol=order.symbol,
            side=order.side,
            shares=shares,
            price=price,
            commission=float(cost.commission),
            slippage=slippage,
            regulatory_fees=float(cost.regulatory_fees),
            slippage_bps=(slippage / gross * 10_000.0) if gross > 0 else 0.0,
            used_unsettled_funds=used_unsettled,
        )
        self.fills.append(fill)
        return fill

    def _reject(self, order: Order, day: date, reason: str) -> Rejection:
        rejection = Rejection(day, order.symbol, order.side, order.shares, reason)
        self.rejections.append(rejection)
        return rejection

    def _settle_date(self, day: date, settlement_days: int) -> date | None:
        index = self._index.get(day)
        if index is None:
            return None
        target = index + settlement_days
        if target < len(self._dates):
            return self._dates[target]
        return None  # settles beyond the backtest window; stays unsettled


def run_backtest(
    *,
    bars: pd.DataFrame,
    target_provider: TargetProvider,
    initial_cash: float,
    cost_model: UsCostModel | None = None,
    instruments: Mapping[str, Instrument] | None = None,
    min_weight_change: float = 0.0,
) -> BacktestResult:
    """Run the daily event loop over ``bars`` and return the full result.

    ``bars`` is the DataRepo read view (columns ``symbol, date, close,
    is_halted``); pass the adjusted view so splits do not jump equity (T5). At
    each session the provider is asked for a target; sells run before buys so
    freed proceeds can fund buys (and correctly trigger a GFV when unsettled).
    """

    if not math.isfinite(min_weight_change) or min_weight_change < 0:
        raise ValueError("min_weight_change must be finite and non-negative")
    instruments = instruments or {}
    frame = _prepare_bars(bars)
    trading_dates = sorted({row_date for row_date in frame["date"].tolist()})
    closes_by_date, halted_by_date = _index_bars(frame)

    engine = BacktestEngine(
        initial_cash=initial_cash, trading_dates=trading_dates, cost_model=cost_model
    )
    warnings: list[str] = []
    last_close: dict[str, float] = {}
    equity_curve: list[EquityPoint] = []

    for day in trading_dates:
        equity = step_session(
            engine,
            day=day,
            closes_today=closes_by_date.get(day, {}),
            halted_today=halted_by_date.get(day, set()),
            last_close=last_close,
            target_provider=target_provider,
            instruments=instruments,
            min_weight_change=min_weight_change,
            warnings=warnings,
        )
        equity_curve.append(EquityPoint(day=day, equity=equity))

    return BacktestResult(
        equity_curve=equity_curve,
        fills=engine.fills,
        rejections=engine.rejections,
        gfv_count=engine.gfv_count,
        final_positions=dict(sorted(engine.positions.items())),
        final_cash=engine.buying_power(),
        initial_cash=float(initial_cash),
        warnings=warnings,
    )


def step_session(
    engine: BacktestEngine,
    *,
    day: date,
    closes_today: Mapping[str, float],
    halted_today: set[str],
    last_close: dict[str, float],
    target_provider: TargetProvider,
    instruments: Mapping[str, Instrument],
    min_weight_change: float = 0.0,
    warnings: list[str],
) -> float:
    """Advance one trading session and return end-of-day equity.

    This is the single source of truth for a day's mechanics — settle, mark,
    ask the provider for a target, rebalance — shared by :func:`run_backtest`
    and the live-shaped :class:`~yquant.paper.broker.PaperBroker`, so the two
    paths are structurally identical (the T7 parity guarantee, 08 §2). Mutates
    ``last_close`` in place with today's closes so a missing quote holds the
    prior mark.
    """

    engine.settle_due(day)
    last_close.update(closes_today)

    target = target_provider(day, closes_today)
    if target is not None:
        if target.as_of != day:
            raise ValueError(
                f"target portfolio as_of {target.as_of.isoformat()} does not match "
                f"session {day.isoformat()}"
            )
        _rebalance(
            engine,
            target=target,
            day=day,
            prices=last_close,
            closes_today=closes_today,
            halted_today=halted_today,
            instruments=instruments,
            min_weight_change=min_weight_change,
            warnings=warnings,
        )
    return engine.equity(last_close)


def _rebalance(
    engine: BacktestEngine,
    *,
    target: TargetPortfolio,
    day: date,
    prices: Mapping[str, float],
    closes_today: Mapping[str, float],
    halted_today: set[str],
    instruments: Mapping[str, Instrument],
    min_weight_change: float,
    warnings: list[str],
) -> None:
    portfolio_value = engine.equity(prices)
    desired: dict[str, int] = {}
    for symbol, weight in target.weights.items():
        price = closes_today.get(symbol)
        if price is None or price <= 0:
            warnings.append(f"{day.isoformat()}: no price for {symbol}; target weight skipped")
            continue
        # Churn guard: skip a symbol whose weight barely moved (03 §5.2 turnover
        # control). Hold the current book by defaulting desired to the position.
        current = engine.positions.get(symbol, 0)
        if min_weight_change > 0.0 and portfolio_value > 0.0:
            current_weight = current * price / portfolio_value
            if abs(weight - current_weight) < min_weight_change:
                desired[symbol] = current
                continue
        desired[symbol] = math.floor(weight * portfolio_value / price)

    symbols = sorted(set(desired) | set(engine.positions))
    sells: list[tuple[str, int]] = []
    buys: list[tuple[str, int]] = []
    for symbol in symbols:
        current = engine.positions.get(symbol, 0)
        delta = desired.get(symbol, 0) - current
        if delta < 0:
            sells.append((symbol, -delta))
        elif delta > 0:
            buys.append((symbol, delta))

    orders: list[tuple[str, int, Side]] = [
        *((symbol, shares, "sell") for symbol, shares in sells),
        *((symbol, shares, "buy") for symbol, shares in buys),
    ]
    for symbol, shares, side in orders:
        price = closes_today.get(symbol)
        instrument = instruments.get(symbol, "etf")
        engine.submit_order(
            Order(symbol=symbol, side=side, shares=shares, instrument=instrument),
            day=day,
            price=price if price is not None else 0.0,
            is_halted=symbol in halted_today,
        )


def _prepare_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "date", "close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"bars missing required columns: {sorted(missing)}")
    frame = bars.loc[:, [c for c in ("symbol", "date", "close", "is_halted") if c in bars.columns]]
    frame = frame.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.date
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if frame["symbol"].eq("").any():
        raise ValueError("bars contain an empty symbol")
    if frame["close"].isna().any() or not frame["close"].map(math.isfinite).all():
        raise ValueError("bars contain non-finite close prices")
    if (frame["close"] <= 0).any():
        raise ValueError("bars contain non-positive close prices")
    duplicates = frame.duplicated(["symbol", "date"], keep=False)
    if duplicates.any():
        raise ValueError("bars contain duplicate symbol/date rows")
    if "is_halted" not in frame.columns:
        frame["is_halted"] = False
    else:
        frame["is_halted"] = frame["is_halted"].fillna(False).astype(bool)
    frame = frame.sort_values(["date", "symbol"]).reset_index(drop=True)
    return frame


def _index_bars(
    frame: pd.DataFrame,
) -> tuple[dict[date, dict[str, float]], dict[date, set[str]]]:
    closes_by_date: dict[date, dict[str, float]] = {}
    halted_by_date: dict[date, set[str]] = {}
    for row in frame.itertuples(index=False):
        row_date: date = row.date
        symbol = str(row.symbol)
        closes_by_date.setdefault(row_date, {})[symbol] = float(row.close)
        if bool(getattr(row, "is_halted", False)):
            halted_by_date.setdefault(row_date, set()).add(symbol)
    return closes_by_date, halted_by_date
