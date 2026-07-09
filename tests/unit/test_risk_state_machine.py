from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest

from yquant.ledger import LedgerStore
from yquant.risk.state_machine import (
    RegimeConfig,
    RegimeInputs,
    RegimeMemory,
    RegimeState,
    RegimeStateMachine,
    composite_to_state,
    score_breadth,
    score_credit,
    score_macro_liquidity,
    score_pillars,
    score_trend,
    score_volatility,
    step,
    weighted_composite,
)


def _bullish() -> RegimeInputs:
    """Inputs that make every pillar score +1."""

    return RegimeInputs(
        spy_close=110.0,
        spy_ma_10m=100.0,
        pct_sectors_above_200d=0.80,
        hy_oas_percentile=0.20,
        hy_oas_change_3m_bp=-80.0,
        hyg_lqd_z=0.5,
        vix_level=13.0,
        vix_term_inversion_days=0,
        rsp_spy_trend_slope=0.2,
        pct_above_200d=0.70,
        nfci=-0.4,
        nfci_change=-0.1,
        curve_10y_3m=0.5,
        usd_change_3m=0.0,
    )


def _bearish() -> RegimeInputs:
    """Inputs that make every pillar score -1."""

    return RegimeInputs(
        spy_close=90.0,
        spy_ma_10m=100.0,
        pct_sectors_above_200d=0.20,
        hy_oas_percentile=0.90,
        hy_oas_change_3m_bp=200.0,
        hyg_lqd_z=-1.5,
        vix_level=35.0,
        vix_term_inversion_days=7,
        rsp_spy_trend_slope=-0.2,
        pct_above_200d=0.20,
        nfci=0.5,
        nfci_change=0.2,
        curve_10y_3m=-0.3,
        usd_change_3m=0.10,
    )


# --- pillar scoring ---------------------------------------------------------


def test_trend_pillar_scores_all_three_values() -> None:
    assert score_trend(_bullish()) == 1
    assert score_trend(_bearish()) == -1
    mixed = RegimeInputs(spy_close=110.0, spy_ma_10m=100.0, pct_sectors_above_200d=0.50)
    assert score_trend(mixed) == 0


def test_credit_pillar_deterioration_and_improvement() -> None:
    assert score_credit(_bearish()) == -1
    assert score_credit(_bullish()) == 1


def test_volatility_pillar_inversion_forces_negative() -> None:
    calm = RegimeInputs(vix_level=13.0, vix_term_inversion_days=0)
    stressed = RegimeInputs(vix_level=18.0, vix_term_inversion_days=6)
    assert score_volatility(calm) == 1
    assert score_volatility(stressed) == -1


def test_breadth_and_macro_liquidity_pillars() -> None:
    assert score_breadth(_bullish()) == 1
    assert score_breadth(_bearish()) == -1
    assert score_macro_liquidity(_bullish()) == 1
    assert score_macro_liquidity(_bearish()) == -1


def test_missing_inputs_yield_none_score() -> None:
    assert score_trend(RegimeInputs()) is None
    assert score_credit(RegimeInputs()) is None
    assert score_volatility(RegimeInputs()) is None
    assert score_breadth(RegimeInputs()) is None
    assert score_macro_liquidity(RegimeInputs()) is None


# --- composite + mapping ----------------------------------------------------


def test_weighted_composite_bounds() -> None:
    cfg = RegimeConfig()
    all_plus = dict.fromkeys(cfg.weights, 1)
    all_minus = dict.fromkeys(cfg.weights, -1)
    assert weighted_composite(all_plus, cfg) == pytest.approx(1.0)
    assert weighted_composite(all_minus, cfg) == pytest.approx(-1.0)


def test_composite_to_state_thresholds() -> None:
    cfg = RegimeConfig()
    assert composite_to_state(1.0, cfg) is RegimeState.RISK_ON
    assert composite_to_state(0.0, cfg) is RegimeState.NEUTRAL
    assert composite_to_state(-0.30, cfg) is RegimeState.RISK_OFF
    assert composite_to_state(-0.80, cfg) is RegimeState.CRISIS


def test_state_severity_ordering() -> None:
    assert RegimeState.RISK_ON.severity < RegimeState.NEUTRAL.severity
    assert RegimeState.NEUTRAL.severity < RegimeState.RISK_OFF.severity
    assert RegimeState.RISK_OFF.severity < RegimeState.CRISIS.severity


# --- stale carry-forward (P10) ---------------------------------------------


def test_stale_pillar_carries_last_score_not_neutral() -> None:
    scores, stale = score_pillars(_bearish(), last_scores={})
    assert stale == []
    # Now feed empty inputs: every pillar is stale and must reuse -1, not 0.
    carried, stale2 = score_pillars(RegimeInputs(), last_scores=scores)
    assert sorted(stale2) == sorted(scores)
    assert carried == scores


def test_missing_data_never_manufactures_a_regime_change() -> None:
    cfg = RegimeConfig(confirm_periods=1)
    machine = RegimeStateMachine(cfg, initial=RegimeState.NEUTRAL)
    # Drive to a committed state via bearish inputs (all pillars -1 → Crisis).
    committed = machine.update(_bearish()).state
    assert committed is RegimeState.CRISIS
    # A day with no data at all must carry forward the scores, not flip state.
    reading = machine.update(RegimeInputs())
    assert reading.state is committed
    assert sorted(reading.stale_pillars) == sorted(cfg.weights)


# --- hysteresis / stateful wrapper -----------------------------------------


def test_confirm_periods_gates_the_switch() -> None:
    cfg = RegimeConfig(confirm_periods=2)
    memory = RegimeMemory.initial(RegimeState.NEUTRAL)
    # First bullish reading: candidate RiskOn but not yet committed.
    memory, r1 = step(memory, _bullish(), cfg)
    assert r1.candidate is RegimeState.RISK_ON
    assert r1.state is RegimeState.NEUTRAL
    # Second consecutive bullish reading: now it commits.
    memory, r2 = step(memory, _bullish(), cfg)
    assert r2.state is RegimeState.RISK_ON


def test_reading_detail_is_json_safe() -> None:
    _, reading = step(RegimeMemory.initial(), _bearish(), RegimeConfig(confirm_periods=1))
    detail = reading.to_detail()
    assert detail["state"] == "Crisis"
    assert set(cast(dict[str, object], detail["pillar_scores"])) == set(RegimeConfig().weights)
    assert isinstance(detail["composite"], float)


# --- config validation ------------------------------------------------------


def test_config_rejects_bad_weights_and_thresholds() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        RegimeConfig(weights={"trend": 0.5, "credit": 0.1, "volatility": 0.1,
                              "breadth": 0.1, "macro_liquidity": 0.1})
    with pytest.raises(ValueError, match="thresholds"):
        RegimeConfig(risk_off_at=0.5)
    with pytest.raises(ValueError, match="confirm_periods"):
        RegimeConfig(confirm_periods=0)


# --- ledger persistence ------------------------------------------------------


def test_regime_history_round_trips_and_upserts(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "yquant.db")
    store.bootstrap()

    _, reading = step(RegimeMemory.initial(), _bearish(), RegimeConfig(confirm_periods=1))
    store.record_regime(
        as_of=date(2024, 3, 12),
        state=reading.state.value,
        composite=reading.composite,
        detail=reading.to_detail(),
        recorded_at_utc=datetime(2024, 3, 12, 21, 0, tzinfo=UTC),
    )
    # Re-record the same date (idempotent replay) — must overwrite, not duplicate.
    store.record_regime(
        as_of=date(2024, 3, 12),
        state="Crisis",
        composite=reading.composite,
        detail={"note": "rerun"},
    )

    rows = store.list_regime_history()
    assert len(rows) == 1
    assert rows[0].date == date(2024, 3, 12)
    assert rows[0].state == "Crisis"
    assert rows[0].detail == {"note": "rerun"}
