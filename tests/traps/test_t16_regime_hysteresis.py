"""T16 (13 §11, 06 §2): the regime state machine must not chatter and must move
between the four states only along the defined severity ladder.

Two guarantees:
  * Hysteresis — a boundary-oscillating input series does not flip the committed
    state on every reading; a change requires ``confirm_periods`` consecutive
    confirmations.
  * Transition matrix — the committed state changes by at most one severity step
    per commit (RiskOn↔Neutral↔RiskOff↔Crisis), never skipping a level within a
    single evaluation once confirmations are required.
"""

from __future__ import annotations

from yquant.risk.state_machine import (
    RegimeConfig,
    RegimeInputs,
    RegimeMemory,
    RegimeState,
    replay,
    step,
)


def _inputs_for_composite(target: float) -> RegimeInputs:
    """Craft inputs whose trend pillar alone drives the composite sign.

    Only the trend pillar (weight 0.30) is populated; every other pillar is
    stale and, from a NEUTRAL start with no prior scores, carries 0. So the
    composite is ``+0.30`` (bullish trend) or ``-0.30`` (bearish trend) — both
    just past the ±0.25 thresholds, i.e. exactly the boundary case that would
    chatter without hysteresis.
    """

    if target > 0:
        return RegimeInputs(spy_close=110.0, spy_ma_10m=100.0, pct_sectors_above_200d=0.80)
    return RegimeInputs(spy_close=90.0, spy_ma_10m=100.0, pct_sectors_above_200d=0.20)


def test_t16_oscillating_boundary_does_not_chatter() -> None:
    """Alternating bullish/bearish readings never commit a switch (streak resets)."""

    cfg = RegimeConfig(confirm_periods=2)
    series = [
        (None, _inputs_for_composite(+1.0)),
        (None, _inputs_for_composite(-1.0)),
        (None, _inputs_for_composite(+1.0)),
        (None, _inputs_for_composite(-1.0)),
        (None, _inputs_for_composite(+1.0)),
    ]
    memory = RegimeMemory.initial(RegimeState.NEUTRAL)
    for _, inputs in series:
        memory, reading = step(memory, inputs, cfg)
        # Candidate flips each step, but the committed state stays NEUTRAL
        # because no candidate is ever confirmed twice in a row.
        assert reading.state is RegimeState.NEUTRAL


def test_t16_two_consecutive_confirmations_commit_the_switch() -> None:
    cfg = RegimeConfig(confirm_periods=2)
    memory = RegimeMemory.initial(RegimeState.NEUTRAL)

    memory, r1 = step(memory, _inputs_for_composite(+1.0), cfg)
    assert r1.state is RegimeState.NEUTRAL and r1.candidate is RegimeState.RISK_ON
    memory, r2 = step(memory, _inputs_for_composite(+1.0), cfg)
    assert r2.state is RegimeState.RISK_ON


def test_t16_committed_state_steps_one_level_at_a_time() -> None:
    """A monotonic slide from RiskOn to Crisis commits without skipping a level."""

    cfg = RegimeConfig(confirm_periods=1)  # commit immediately to inspect the path

    memory = RegimeMemory.initial(RegimeState.RISK_ON)
    ladder = [
        (_all_pillars("neutral"), RegimeState.NEUTRAL),
        (_all_pillars("risk_off"), RegimeState.RISK_OFF),
        (_all_pillars("crisis"), RegimeState.CRISIS),
    ]
    seen = [memory.state]
    for inputs, _ in ladder:
        memory, reading = step(memory, inputs, cfg)
        seen.append(reading.state)

    order = [
        RegimeState.RISK_ON,
        RegimeState.NEUTRAL,
        RegimeState.RISK_OFF,
        RegimeState.CRISIS,
    ]
    # Each committed transition moves exactly one rung down the ladder.
    for prev, cur in zip(seen[:-1], seen[1:], strict=True):
        assert order.index(cur) - order.index(prev) == 1


def test_t16_transition_matrix_is_symmetric_on_recovery() -> None:
    """Climbing back from Crisis to RiskOn also steps one level per confirmation."""

    cfg = RegimeConfig(confirm_periods=1)
    memory = RegimeMemory.initial(RegimeState.CRISIS)
    recovery = [
        (_all_pillars("risk_off"), RegimeState.RISK_OFF),
        (_all_pillars("neutral"), RegimeState.NEUTRAL),
        (_all_pillars("bullish"), RegimeState.RISK_ON),
    ]
    for inputs, expected in recovery:
        memory, reading = step(memory, inputs, cfg)
        assert reading.state is expected


def _all_pillars(kind: str) -> RegimeInputs:
    """Full five-pillar inputs whose composite lands in the named band."""

    if kind == "bullish":  # composite +1.0 → RiskOn
        return RegimeInputs(
            spy_close=110.0, spy_ma_10m=100.0, pct_sectors_above_200d=0.80,
            hy_oas_percentile=0.20, hy_oas_change_3m_bp=-80.0, hyg_lqd_z=0.5,
            vix_level=13.0, vix_term_inversion_days=0,
            rsp_spy_trend_slope=0.2, pct_above_200d=0.70,
            nfci=-0.4, nfci_change=-0.1, curve_10y_3m=0.5, usd_change_3m=0.0,
        )
    if kind == "neutral":  # every pillar 0 → composite 0.0 → Neutral
        return RegimeInputs(
            spy_close=100.0, spy_ma_10m=100.0, pct_sectors_above_200d=0.50,
            hy_oas_percentile=0.50, hy_oas_change_3m_bp=0.0, hyg_lqd_z=-0.5,
            vix_level=20.0, vix_term_inversion_days=2,
            rsp_spy_trend_slope=0.0, pct_above_200d=0.50,
            nfci=0.1, nfci_change=-0.1, curve_10y_3m=0.2, usd_change_3m=0.0,
        )
    if kind == "risk_off":  # composite -0.30 (between -0.25 and -0.60) → RiskOff
        # Trend and breadth negative (0.40 weight); others neutral.
        return RegimeInputs(
            spy_close=90.0, spy_ma_10m=100.0, pct_sectors_above_200d=0.20,
            hy_oas_percentile=0.50, hy_oas_change_3m_bp=0.0, hyg_lqd_z=-0.5,
            vix_level=20.0, vix_term_inversion_days=2,
            rsp_spy_trend_slope=-0.2, pct_above_200d=0.20,
            nfci=0.1, nfci_change=-0.1, curve_10y_3m=0.2, usd_change_3m=0.0,
        )
    if kind == "crisis":  # every pillar -1 → composite -1.0 → Crisis
        return RegimeInputs(
            spy_close=90.0, spy_ma_10m=100.0, pct_sectors_above_200d=0.20,
            hy_oas_percentile=0.90, hy_oas_change_3m_bp=200.0, hyg_lqd_z=-1.5,
            vix_level=35.0, vix_term_inversion_days=7,
            rsp_spy_trend_slope=-0.2, pct_above_200d=0.20,
            nfci=0.5, nfci_change=0.2, curve_10y_3m=-0.3, usd_change_3m=0.10,
        )
    raise ValueError(kind)


def test_t16_replay_is_deterministic() -> None:
    """Same dated series → identical committed-state path on every replay."""

    import datetime as dt

    series = [
        (dt.date(2020, 2, 21), _all_pillars("neutral")),
        (dt.date(2020, 2, 28), _all_pillars("risk_off")),
        (dt.date(2020, 3, 6), _all_pillars("risk_off")),
        (dt.date(2020, 3, 13), _all_pillars("crisis")),
        (dt.date(2020, 3, 20), _all_pillars("crisis")),
    ]
    cfg = RegimeConfig(confirm_periods=2)
    first = [(d, r.state) for d, r in replay(series, cfg)]
    second = [(d, r.state) for d, r in replay(series, cfg)]
    assert first == second
