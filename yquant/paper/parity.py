"""T7 dual-engine parity + shadow (L1) reconciliation (06 §2 T7, 08 §1-§2).

Parity is the honesty proof: the backtest and the PaperBroker run the identical
constraint core (:func:`yquant.backtest.engine.step_session`), so their equity
curves must track to within **2 bps daily / 20 bps cumulative** (T7). We compute
those drifts explicitly and expose them as a report the CI gate and the L1 shadow
report (≥20 sessions, 08 §1) consume. Because the two paths share one accounting
step, a non-zero drift means an accounting *bug*, not model noise — which is the
whole point of the test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from yquant.backtest.engine import BacktestResult, TargetProvider, run_backtest
from yquant.paper.broker import PaperConfig, run_paper

# T7 thresholds (06 §2).
_DAILY_BPS_CAP = 2.0
_CUMULATIVE_BPS_CAP = 20.0
_BPS = 10_000.0


@dataclass(frozen=True)
class ParityReport:
    """One backtest-vs-paper comparison, JSON-safe for the ledger / CI gate."""

    sessions: int
    max_daily_bps: float
    cumulative_bps: float
    daily_cap_bps: float
    cumulative_cap_bps: float
    worst_day: str | None
    backtest_digest: str
    paper_digest: str
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "sessions": self.sessions,
            "max_daily_bps": round(self.max_daily_bps, 6),
            "cumulative_bps": round(self.cumulative_bps, 6),
            "daily_cap_bps": self.daily_cap_bps,
            "cumulative_cap_bps": self.cumulative_cap_bps,
            "worst_day": self.worst_day,
            "backtest_digest": self.backtest_digest,
            "paper_digest": self.paper_digest,
            "passed": self.passed,
        }


def _equity_by_day(result: BacktestResult) -> dict[date, float]:
    return {point.day: point.equity for point in result.equity_curve}


def compare_curves(
    backtest: BacktestResult,
    paper: BacktestResult,
    *,
    daily_cap_bps: float = _DAILY_BPS_CAP,
    cumulative_cap_bps: float = _CUMULATIVE_BPS_CAP,
) -> ParityReport:
    """Compare two equity curves under the T7 daily / cumulative bps caps."""

    bt = _equity_by_day(backtest)
    pp = _equity_by_day(paper)
    common = sorted(set(bt) & set(pp))
    same_sessions = set(bt) == set(pp)

    max_daily_bps = 0.0
    worst_day: str | None = None
    for day in common:
        base = bt[day]
        if base == 0.0:
            continue
        drift = abs(pp[day] - base) / abs(base) * _BPS
        if drift > max_daily_bps:
            max_daily_bps = drift
            worst_day = day.isoformat()

    cumulative_bps = 0.0
    if common:
        last = common[-1]
        base = bt[last]
        if base != 0.0:
            cumulative_bps = abs(pp[last] - base) / abs(base) * _BPS

    passed = (
        len(common) > 0
        and same_sessions
        and max_daily_bps <= daily_cap_bps
        and cumulative_bps <= cumulative_cap_bps
        and backtest.digest() == paper.digest()
    )
    return ParityReport(
        sessions=len(common),
        max_daily_bps=max_daily_bps,
        cumulative_bps=cumulative_bps,
        daily_cap_bps=daily_cap_bps,
        cumulative_cap_bps=cumulative_cap_bps,
        worst_day=worst_day,
        backtest_digest=backtest.digest(),
        paper_digest=paper.digest(),
        passed=passed,
    )


def parity_report(
    *,
    bars: pd.DataFrame,
    provider_factory: object,
    initial_cash: float,
    config: PaperConfig | None = None,
) -> ParityReport:
    """Run both engines over ``bars`` and return the T7 parity report.

    ``provider_factory`` is a zero-arg callable returning a fresh
    :data:`TargetProvider`; a fresh instance is used for each engine so provider
    state cannot leak between the two runs (the same discipline P6 uses).
    """

    if not callable(provider_factory):
        raise TypeError("provider_factory must be a zero-arg callable returning a TargetProvider")

    cfg = _config_with_cash(config, initial_cash)
    backtest = run_backtest(
        bars=bars,
        target_provider=_as_provider(provider_factory()),
        initial_cash=initial_cash,
        cost_model=cfg.cost_model,
        instruments=cfg.instruments,
        min_weight_change=cfg.min_weight_change,
    )
    paper = run_paper(
        bars=bars, target_provider=_as_provider(provider_factory()), config=cfg
    ).result()
    return compare_curves(backtest, paper)


def _config_with_cash(config: PaperConfig | None, initial_cash: float) -> PaperConfig:
    """Return a config whose ``initial_cash`` matches the parity run's cash."""

    if config is None:
        return PaperConfig(initial_cash=initial_cash)
    if config.initial_cash == initial_cash:
        return config
    return PaperConfig(
        initial_cash=initial_cash,
        cost_model=config.cost_model,
        instruments=config.instruments,
        min_weight_change=config.min_weight_change,
        reconcile_tolerance_usd=config.reconcile_tolerance_usd,
    )


def _as_provider(candidate: object) -> TargetProvider:
    if not callable(candidate):
        raise TypeError("provider factory must return a callable TargetProvider")
    return candidate  # type: ignore[return-value]


@dataclass(frozen=True)
class ShadowReport:
    """L1 shadow report: ≥20 sessions of parity + reconciliation health (08 §1)."""

    parity: ParityReport
    min_sessions: int
    reconciliation_breaches: int
    meets_min_sessions: bool
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "parity": self.parity.as_dict(),
            "min_sessions": self.min_sessions,
            "reconciliation_breaches": self.reconciliation_breaches,
            "meets_min_sessions": self.meets_min_sessions,
            "passed": self.passed,
        }


def shadow_reconciliation(
    *,
    bars: pd.DataFrame,
    provider_factory: object,
    initial_cash: float,
    config: PaperConfig | None = None,
    min_sessions: int = 20,
) -> ShadowReport:
    """Produce the L1 shadow report (parity + ≥``min_sessions`` + zero breaches)."""

    if not callable(provider_factory):
        raise TypeError("provider_factory must be a zero-arg callable")

    cfg = _config_with_cash(config, initial_cash)
    backtest = run_backtest(
        bars=bars,
        target_provider=_as_provider(provider_factory()),
        initial_cash=initial_cash,
        cost_model=cfg.cost_model,
        instruments=cfg.instruments,
        min_weight_change=cfg.min_weight_change,
    )
    broker = run_paper(bars=bars, target_provider=_as_provider(provider_factory()), config=cfg)
    parity = compare_curves(backtest, broker.result())
    breaches = sum(1 for tick in broker.reconciliations if not tick.balanced)
    meets = parity.sessions >= min_sessions
    return ShadowReport(
        parity=parity,
        min_sessions=min_sessions,
        reconciliation_breaches=breaches,
        meets_min_sessions=meets,
        passed=parity.passed and meets and breaches == 0,
    )


__all__ = [
    "ParityReport",
    "ShadowReport",
    "compare_curves",
    "parity_report",
    "shadow_reconciliation",
]
