"""PaperBroker: a live-shaped driver over the shared backtest constraint core (08 §2).

The plan makes an unusual but load-bearing promise: *honesty is structurally
guaranteed by T7 dual-engine parity*. We realise that literally — the paper path
does not re-implement settlement, whole-share lots, GFV counting, halt rejection
or the cost model. It reuses :func:`yquant.backtest.engine.step_session`, the one
source of truth a backtest also runs. The only difference from a batch backtest is
*shape*: quotes are handed in one session at a time (as a live feed would deliver
them), a daily P1/P2 reconciliation runs at each close, and a books-don't-balance
event freezes the next session's auto-trading (08 §2). Because both paths execute
the identical accounting step, the equity curves agree to the cent and T7 parity
is ~0 bps by construction rather than by luck.

The *execution* nuance the plan describes — T+1 open fills at ``open×(1±slippage)``
clamped to ``[low, high]`` — is real-world friction that separates "hypothesis
error" from "execution error" (08 §3, the digital twin). That belongs to the
execution-quality backfill (:mod:`yquant.paper.execution`), not to the parity
core, so the twin's frictionless mark stays comparable to the backtest.

Pure and deterministic: no wall-clock, no IO. A paper session over the same bars
reproduces bit-for-bit, so the whole run is replayable (07).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from yquant.backtest.costs import Instrument, UsCostModel
from yquant.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    EquityPoint,
    TargetProvider,
    _index_bars,
    _prepare_bars,
    step_session,
)

# 08 §1: the sim-account (L2) runs a virtual $50,000 book.
DEFAULT_PAPER_CASH = 50_000.0


@dataclass(frozen=True)
class PaperConfig:
    """Sim-account parameters (08 §1-§2)."""

    initial_cash: float = DEFAULT_PAPER_CASH
    cost_model: UsCostModel = field(default_factory=UsCostModel)
    instruments: Mapping[str, Instrument] = field(default_factory=dict)
    min_weight_change: float = 0.0
    # Reconciliation must balance to the cent (08 §2 "分毫必平").
    reconcile_tolerance_usd: float = 0.005


@dataclass(frozen=True)
class ReconcileTick:
    """One session's P1/P2 double-entry reconciliation outcome."""

    day: date
    balanced: bool
    p1_diff_usd: float
    p2_diff_usd: float
    frozen_next_session: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "day": self.day.isoformat(),
            "balanced": self.balanced,
            "p1_diff_usd": round(self.p1_diff_usd, 6),
            "p2_diff_usd": round(self.p2_diff_usd, 6),
            "frozen_next_session": self.frozen_next_session,
        }


class PaperBroker:
    """A live-shaped wrapper over :class:`BacktestEngine` with daily reconciliation.

    Feed sessions in date order via :meth:`on_session`. On a books-don't-balance
    tick the broker records an S1-worthy breach and freezes the *next* session's
    auto-trading (the target is ignored, only settlement/marking run) exactly as
    08 §2 requires. State is otherwise the shared constraint engine, so a paper
    run and a backtest over the same bars yield the same fills.
    """

    def __init__(
        self,
        *,
        trading_dates: list[date],
        config: PaperConfig | None = None,
    ) -> None:
        self._config = config or PaperConfig()
        self._engine = BacktestEngine(
            initial_cash=self._config.initial_cash,
            trading_dates=trading_dates,
            cost_model=self._config.cost_model,
        )
        self._last_close: dict[str, float] = {}
        self._equity_curve: list[EquityPoint] = []
        self._warnings: list[str] = []
        self._reconciliations: list[ReconcileTick] = []
        self._frozen = False

    @property
    def frozen(self) -> bool:
        """True when a prior unbalanced close froze auto-trading for this session."""

        return self._frozen

    @property
    def reconciliations(self) -> list[ReconcileTick]:
        return list(self._reconciliations)

    def on_session(
        self,
        *,
        day: date,
        closes_today: Mapping[str, float],
        halted_today: set[str] | None = None,
        target_provider: TargetProvider,
    ) -> EquityPoint:
        """Process one trading session and return its end-of-day equity point.

        When frozen from a prior breach, the target provider is bypassed so only
        settlement and marking run — the safety valve 08 §2 mandates.
        """

        frozen_now = self._frozen
        effective_provider: TargetProvider = (
            (lambda _day, _closes: None) if frozen_now else target_provider
        )
        equity = step_session(
            self._engine,
            day=day,
            closes_today=closes_today,
            halted_today=halted_today or set(),
            last_close=self._last_close,
            target_provider=effective_provider,
            instruments=self._config.instruments,
            min_weight_change=self._config.min_weight_change,
            warnings=self._warnings,
        )
        point = EquityPoint(day=day, equity=equity)
        self._equity_curve.append(point)
        self._reconcile(day, equity)
        return point

    def _reconcile(self, day: date, curve_equity: float) -> None:
        """P1 (cash from fills) and P2 (cash + marks) must match to the cent."""

        reconstructed = self._config.initial_cash
        for fill in self._engine.fills:
            if fill.side == "buy":
                reconstructed -= fill.gross + fill.cost_total
            else:
                reconstructed += fill.gross - fill.cost_total
        p1_diff = abs(reconstructed - self._engine.buying_power())

        marked = sum(
            shares * self._last_close.get(symbol, 0.0)
            for symbol, shares in self._engine.positions.items()
        )
        recomputed = self._engine.buying_power() + marked
        p2_diff = abs(curve_equity - recomputed)

        tol = self._config.reconcile_tolerance_usd
        balanced = p1_diff <= tol and p2_diff <= tol
        # A breach freezes the *next* session (08 §2); this session already ran.
        self._frozen = not balanced
        self._reconciliations.append(
            ReconcileTick(
                day=day,
                balanced=balanced,
                p1_diff_usd=p1_diff,
                p2_diff_usd=p2_diff,
                frozen_next_session=not balanced,
            )
        )

    def result(self) -> BacktestResult:
        """Snapshot the paper book as a :class:`BacktestResult` (parity-comparable)."""

        return BacktestResult(
            equity_curve=list(self._equity_curve),
            fills=list(self._engine.fills),
            rejections=list(self._engine.rejections),
            gfv_count=self._engine.gfv_count,
            final_positions=dict(sorted(self._engine.positions.items())),
            final_cash=self._engine.buying_power(),
            initial_cash=float(self._config.initial_cash),
            warnings=list(self._warnings),
        )


def run_paper(
    *,
    bars: pd.DataFrame,
    target_provider: TargetProvider,
    config: PaperConfig | None = None,
) -> PaperBroker:
    """Drive a PaperBroker session-by-session over ``bars`` (live-shaped replay).

    ``bars`` is the DataRepo read view (pass the adjusted view so splits do not
    jump equity, T5). Returns the broker so callers can read its reconciliation
    ledger and freeze state as well as :meth:`PaperBroker.result`.
    """

    frame = _prepare_bars(bars)
    trading_dates = sorted({row_date for row_date in frame["date"].tolist()})
    closes_by_date, halted_by_date = _index_bars(frame)

    broker = PaperBroker(trading_dates=trading_dates, config=config)
    for day in trading_dates:
        broker.on_session(
            day=day,
            closes_today=closes_by_date.get(day, {}),
            halted_today=halted_by_date.get(day, set()),
            target_provider=target_provider,
        )
    return broker


def build_paper_result(
    *,
    bars: pd.DataFrame,
    target_provider: TargetProvider,
    config: PaperConfig | None = None,
) -> BacktestResult:
    """Convenience: run the paper path and return just its :class:`BacktestResult`."""

    return run_paper(bars=bars, target_provider=target_provider, config=config).result()


__all__ = [
    "DEFAULT_PAPER_CASH",
    "PaperBroker",
    "PaperConfig",
    "ReconcileTick",
    "build_paper_result",
    "run_paper",
]
