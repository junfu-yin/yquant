"""M9 Layer-1 regime state machine (13 §4, 03 §5 M9).

Five pillars each score -1/0/+1 from global-macro observables; a weighted
composite maps to one of four states ``RiskOn / Neutral / RiskOff / Crisis``.
Switching is guarded by hysteresis (a differing candidate must persist for
``confirm_periods`` consecutive evaluations, default two weekly runs) so a
one-off blip cannot flip the regime — this is the anti-chatter guarantee T16
exercises.

The job of the machine is not prediction but *describing the climate and
authorising / vetoing action*: M8 reads the state to tighten the vol target in
RiskOff and to force leveraged sleeves to zero in Crisis (13 §4).

Kept standard-library only and side-effect free. Deriving the observables
(10-month MA, OAS percentile, VIX term structure, …) from a DataRepo belongs to
an adapter; this module operates on the already-derived numbers so it stays
pure and fully replayable (07).

Missing pillar inputs are carried forward from the last known score and flagged
``stale`` rather than silently defaulting to neutral — this realises P10 (state
machine availability): a data gap never manufactures a regime change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

TREND = "trend"
CREDIT = "credit"
VOLATILITY = "volatility"
BREADTH = "breadth"
MACRO_LIQUIDITY = "macro_liquidity"

PILLARS = (TREND, CREDIT, VOLATILITY, BREADTH, MACRO_LIQUIDITY)


class RegimeState(StrEnum):
    """The four market-climate states, ordered from calm to stressed."""

    RISK_ON = "RiskOn"
    NEUTRAL = "Neutral"
    RISK_OFF = "RiskOff"
    CRISIS = "Crisis"

    @property
    def severity(self) -> int:
        """0 (RiskOn) … 3 (Crisis); higher means M8 should de-risk harder."""

        return _SEVERITY[self]


_SEVERITY = {
    RegimeState.RISK_ON: 0,
    RegimeState.NEUTRAL: 1,
    RegimeState.RISK_OFF: 2,
    RegimeState.CRISIS: 3,
}


@dataclass(frozen=True)
class RegimeConfig:
    """Tunable thresholds and weights (13 §4 defaults).

    Weights follow the pillars' evidence grades: trend (A-) carries the most,
    credit (B+) next, then macro liquidity / volatility (B), then breadth (B-).
    They must be positive and sum to 1.
    """

    weights: Mapping[str, float] = field(
        default_factory=lambda: {
            TREND: 0.30,
            CREDIT: 0.25,
            VOLATILITY: 0.20,
            MACRO_LIQUIDITY: 0.15,
            BREADTH: 0.10,
        }
    )
    risk_on_at: float = 0.25
    risk_off_at: float = -0.25
    crisis_at: float = -0.60
    confirm_periods: int = 2

    def __post_init__(self) -> None:
        missing = set(PILLARS) - set(self.weights)
        if missing:
            raise ValueError(f"weights missing pillars: {sorted(missing)}")
        if any(w <= 0 for w in self.weights.values()):
            raise ValueError("all pillar weights must be positive")
        if abs(sum(self.weights.values()) - 1.0) > 1e-9:
            raise ValueError("pillar weights must sum to 1")
        if not (self.crisis_at < self.risk_off_at < self.risk_on_at):
            raise ValueError("thresholds must satisfy crisis_at < risk_off_at < risk_on_at")
        if self.confirm_periods < 1:
            raise ValueError("confirm_periods must be >= 1")


@dataclass(frozen=True)
class RegimeInputs:
    """Derived observables feeding the five pillars; any field may be ``None``.

    A pillar whose required inputs are missing is treated as stale (its previous
    score is carried forward), never as a fresh neutral reading.
    """

    # Trend pillar
    spy_close: float | None = None
    spy_ma_10m: float | None = None
    pct_sectors_above_200d: float | None = None
    # Credit pillar
    hy_oas_percentile: float | None = None
    hy_oas_change_3m_bp: float | None = None
    hyg_lqd_z: float | None = None
    # Volatility pillar
    vix_level: float | None = None
    vix_term_inversion_days: int | None = None
    # Breadth pillar
    rsp_spy_trend_slope: float | None = None
    pct_above_200d: float | None = None
    # Macro-liquidity pillar
    nfci: float | None = None
    nfci_change: float | None = None
    curve_10y_3m: float | None = None
    usd_change_3m: float | None = None


@dataclass(frozen=True)
class RegimeReading:
    """One evaluation's output: committed state plus full explainability."""

    state: RegimeState
    candidate: RegimeState
    composite: float
    pillar_scores: dict[str, int]
    stale_pillars: list[str]

    def to_detail(self) -> dict[str, object]:
        """JSON-safe payload for ``regime_history`` / risk-event ledger rows."""

        return {
            "state": self.state.value,
            "candidate": self.candidate.value,
            "composite": round(self.composite, 6),
            "pillar_scores": dict(sorted(self.pillar_scores.items())),
            "stale_pillars": list(self.stale_pillars),
        }


@dataclass(frozen=True)
class RegimeMemory:
    """Carried state between evaluations (hysteresis + stale carry-forward)."""

    state: RegimeState
    pending: RegimeState | None = None
    pending_streak: int = 0
    last_scores: dict[str, int] = field(default_factory=dict)

    @classmethod
    def initial(cls, state: RegimeState = RegimeState.NEUTRAL) -> RegimeMemory:
        return cls(state=state, pending=None, pending_streak=0, last_scores={})


def score_trend(inputs: RegimeInputs) -> int | None:
    """SPY vs its 10-month MA, corroborated by sector breadth above the 200d."""

    if (
        inputs.spy_close is None
        or inputs.spy_ma_10m is None
        or inputs.pct_sectors_above_200d is None
    ):
        return None
    above = inputs.spy_close > inputs.spy_ma_10m
    if above and inputs.pct_sectors_above_200d >= 0.60:
        return 1
    if not above and inputs.pct_sectors_above_200d <= 0.40:
        return -1
    return 0


def score_credit(inputs: RegimeInputs) -> int | None:
    """HY OAS level/percentile and 3-month change, plus the HYG/LQD ratio z.

    Deterioration (wide/widening spreads or a stressed HYG/LQD ratio) scores -1;
    a benign, tightening-spread backdrop scores +1.
    """

    if (
        inputs.hy_oas_percentile is None
        or inputs.hy_oas_change_3m_bp is None
        or inputs.hyg_lqd_z is None
    ):
        return None
    deteriorating = (
        inputs.hy_oas_change_3m_bp > 150.0
        or inputs.hy_oas_percentile >= 0.80
        or inputs.hyg_lqd_z <= -1.0
    )
    if deteriorating:
        return -1
    improving = (
        inputs.hy_oas_change_3m_bp < -50.0
        and inputs.hy_oas_percentile <= 0.40
        and inputs.hyg_lqd_z >= 0.0
    )
    if improving:
        return 1
    return 0


def score_volatility(inputs: RegimeInputs) -> int | None:
    """VIX level band and VIX/VIX3M inversion (backwardation = stress)."""

    if inputs.vix_level is None or inputs.vix_term_inversion_days is None:
        return None
    if inputs.vix_level >= 30.0 or inputs.vix_term_inversion_days >= 5:
        return -1
    if inputs.vix_level <= 15.0 and inputs.vix_term_inversion_days == 0:
        return 1
    return 0


def score_breadth(inputs: RegimeInputs) -> int | None:
    """RSP/SPY relative-strength trend and the share of names above the 200d."""

    if inputs.rsp_spy_trend_slope is None or inputs.pct_above_200d is None:
        return None
    if inputs.rsp_spy_trend_slope > 0 and inputs.pct_above_200d >= 0.60:
        return 1
    if inputs.rsp_spy_trend_slope < 0 and inputs.pct_above_200d <= 0.40:
        return -1
    return 0


def score_macro_liquidity(inputs: RegimeInputs) -> int | None:
    """NFCI direction, the 10Y-3M curve, and the 3-month USD move.

    Two or more tightening signals score -1; an outright easy backdrop (NFCI
    below zero and no tightening signals) scores +1.
    """

    if (
        inputs.nfci is None
        or inputs.nfci_change is None
        or inputs.curve_10y_3m is None
        or inputs.usd_change_3m is None
    ):
        return None
    tightening = inputs.nfci > 0.0 and inputs.nfci_change > 0.0
    inverted = inputs.curve_10y_3m < 0.0
    usd_strong = inputs.usd_change_3m > 0.05
    negatives = sum((tightening, inverted, usd_strong))
    if negatives >= 2:
        return -1
    if negatives == 0 and inputs.nfci < 0.0:
        return 1
    return 0


_SCORERS = {
    TREND: score_trend,
    CREDIT: score_credit,
    VOLATILITY: score_volatility,
    BREADTH: score_breadth,
    MACRO_LIQUIDITY: score_macro_liquidity,
}


def score_pillars(
    inputs: RegimeInputs,
    last_scores: Mapping[str, int],
) -> tuple[dict[str, int], list[str]]:
    """Score every pillar, carrying forward the last value where inputs are stale."""

    scores: dict[str, int] = {}
    stale: list[str] = []
    for name in PILLARS:
        value = _SCORERS[name](inputs)
        if value is None:
            stale.append(name)
            scores[name] = last_scores.get(name, 0)
        else:
            scores[name] = value
    return scores, sorted(stale)


def weighted_composite(scores: Mapping[str, int], config: RegimeConfig) -> float:
    """Weighted pillar sum in [-1, +1] (weights sum to 1, scores in {-1,0,1})."""

    return sum(config.weights[name] * scores[name] for name in PILLARS)


def composite_to_state(composite: float, config: RegimeConfig) -> RegimeState:
    """Map a composite score to a candidate state (before hysteresis)."""

    if composite <= config.crisis_at:
        return RegimeState.CRISIS
    if composite <= config.risk_off_at:
        return RegimeState.RISK_OFF
    if composite < config.risk_on_at:
        return RegimeState.NEUTRAL
    return RegimeState.RISK_ON


def _apply_hysteresis(
    memory: RegimeMemory,
    candidate: RegimeState,
    confirm_periods: int,
) -> tuple[RegimeState, RegimeState | None, int]:
    """Commit a state change only after ``confirm_periods`` consecutive candidates."""

    if candidate == memory.state:
        return memory.state, None, 0
    streak = memory.pending_streak + 1 if memory.pending == candidate else 1
    if streak >= confirm_periods:
        return candidate, None, 0
    return memory.state, candidate, streak


def step(
    memory: RegimeMemory,
    inputs: RegimeInputs,
    config: RegimeConfig | None = None,
) -> tuple[RegimeMemory, RegimeReading]:
    """Advance the machine by one evaluation; pure and deterministic.

    Returns the next memory (feed it back on the following call) and the reading
    for this evaluation.
    """

    cfg = config or RegimeConfig()
    scores, stale = score_pillars(inputs, memory.last_scores)
    composite = weighted_composite(scores, cfg)
    candidate = composite_to_state(composite, cfg)
    state, pending, streak = _apply_hysteresis(memory, candidate, cfg.confirm_periods)

    merged = dict(memory.last_scores)
    merged.update(scores)
    next_memory = RegimeMemory(
        state=state, pending=pending, pending_streak=streak, last_scores=merged
    )
    reading = RegimeReading(
        state=state,
        candidate=candidate,
        composite=composite,
        pillar_scores=scores,
        stale_pillars=stale,
    )
    return next_memory, reading


class RegimeStateMachine:
    """Thin stateful wrapper over :func:`step` for the scheduler / backtest loop."""

    def __init__(
        self,
        config: RegimeConfig | None = None,
        initial: RegimeState = RegimeState.NEUTRAL,
    ) -> None:
        self._config = config or RegimeConfig()
        self._memory = RegimeMemory.initial(initial)

    @property
    def state(self) -> RegimeState:
        return self._memory.state

    def update(self, inputs: RegimeInputs) -> RegimeReading:
        """Fold one evaluation into the machine and return its reading."""

        self._memory, reading = step(self._memory, inputs, self._config)
        return reading


def replay(
    inputs_by_date: list[tuple[date, RegimeInputs]],
    config: RegimeConfig | None = None,
    initial: RegimeState = RegimeState.NEUTRAL,
) -> list[tuple[date, RegimeReading]]:
    """Fold a dated input series into per-date readings (full-history backtest)."""

    cfg = config or RegimeConfig()
    memory = RegimeMemory.initial(initial)
    out: list[tuple[date, RegimeReading]] = []
    for as_of, inputs in inputs_by_date:
        memory, reading = step(memory, inputs, cfg)
        out.append((as_of, reading))
    return out


__all__ = [
    "PILLARS",
    "TREND",
    "CREDIT",
    "VOLATILITY",
    "BREADTH",
    "MACRO_LIQUIDITY",
    "RegimeState",
    "RegimeConfig",
    "RegimeInputs",
    "RegimeReading",
    "RegimeMemory",
    "RegimeStateMachine",
    "score_pillars",
    "score_trend",
    "score_credit",
    "score_volatility",
    "score_breadth",
    "score_macro_liquidity",
    "weighted_composite",
    "composite_to_state",
    "step",
    "replay",
]
