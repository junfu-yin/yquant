"""WP8 QA metrics + golden dataset + panel (06 §1, §4, §8)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import cast

import pandas as pd

from yquant.backtest.engine import TargetProvider, run_backtest
from yquant.datasrc.bars import repo_view
from yquant.datasrc.reconcile import reconcile_daily_bars
from yquant.qa import (
    GOLDEN_UNIVERSE,
    GOLDEN_WINDOWS,
    build_golden_bars,
    build_panel,
    check_p1_accounting_conservation,
    check_p2_nav_double_calc,
    check_p3_source_consistency,
    check_p4_adjusted_price_continuity,
    check_p6_digest_reproducible,
    check_p10_state_machine_availability,
    check_p11_layer_budget,
    golden_content_hash,
    golden_manifest,
)
from yquant.qa.metrics import MetricResult, last_close_by_symbol
from yquant.risk.state_machine import RegimeInputs, replay
from yquant.strategies.base import TargetPortfolio


def _core_provider_factory() -> Callable[[], TargetProvider]:
    def factory() -> TargetProvider:
        placed = {"done": False}

        def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
            if placed["done"] or "SPY" not in closes or "TLT" not in closes:
                return None
            placed["done"] = True
            return TargetPortfolio(
                as_of=day,
                weights={"SPY": 0.5, "TLT": 0.4},
                layers={"SPY": "core", "TLT": "core"},
                cash_weight=0.1,
            )

        return provider

    return factory


# ---- Golden dataset --------------------------------------------------------


def test_golden_content_hash_is_deterministic() -> None:
    for window in GOLDEN_WINDOWS:
        assert golden_content_hash(window.key) == golden_content_hash(window.key)


def test_golden_windows_hashes_are_distinct() -> None:
    hashes = {golden_content_hash(w.key) for w in GOLDEN_WINDOWS}
    assert len(hashes) == len(GOLDEN_WINDOWS)


def test_golden_bars_cover_full_universe_and_business_days() -> None:
    bars = build_golden_bars("2023_svb")
    assert set(bars["symbol"]) == set(GOLDEN_UNIVERSE)
    weekdays = pd.to_datetime(bars["date"]).dt.weekday
    assert weekdays.max() <= 4  # Mon-Fri only


def test_golden_manifest_content_hash_matches_bars() -> None:
    manifest = golden_manifest("2020_covid")
    assert manifest.content_hash == golden_content_hash("2020_covid")
    assert manifest.dataset == "golden:2020_covid"
    assert manifest.source == "golden"


# ---- P1 / P2 ---------------------------------------------------------------


def test_p1_accounting_conservation_holds_on_backtest() -> None:
    bars = repo_view(build_golden_bars("2020_covid"))
    result = run_backtest(
        bars=bars, target_provider=_core_provider_factory()(), initial_cash=50_000.0
    )
    p1 = check_p1_accounting_conservation(result)
    assert p1.passed
    assert p1.severity == "block"


def test_p2_nav_double_calc_holds_on_backtest() -> None:
    bars = repo_view(build_golden_bars("2020_covid"))
    result = run_backtest(
        bars=bars, target_provider=_core_provider_factory()(), initial_cash=50_000.0
    )
    p2 = check_p2_nav_double_calc(result, last_close_by_symbol(bars))
    assert p2.passed


def test_p1_conservation_holds_across_a_sell() -> None:
    # Buy on day one, then trim to cash mid-window so the sell branch of the
    # reconstruction (add gross - fees) is exercised, not just buys.
    bars = repo_view(build_golden_bars("2020_covid"))
    sell_after = sorted({d for d in bars["date"]})[3]

    def provider(day: date, closes: Mapping[str, float]) -> TargetPortfolio | None:
        if "SPY" not in closes:
            return None
        if day <= sell_after:
            return TargetPortfolio(
                as_of=day, weights={"SPY": 0.8}, layers={"SPY": "core"}, cash_weight=0.2
            )
        return TargetPortfolio(as_of=day, weights={}, layers={}, cash_weight=1.0)

    result = run_backtest(bars=bars, target_provider=provider, initial_cash=50_000.0)
    assert any(f.side == "sell" for f in result.fills)
    assert check_p1_accounting_conservation(result).passed


# ---- P3 --------------------------------------------------------------------


def test_p3_source_consistency_passes_on_identical_slices() -> None:
    left = build_golden_bars("2024_carry")
    right = left.copy()
    right["source"] = "stooq"
    report = reconcile_daily_bars(left, right, left_source="golden", right_source="stooq")
    p3 = check_p3_source_consistency(report)
    assert p3.passed
    assert p3.detail["consistency_rate"] == 1.0


def test_p3_source_consistency_fails_when_prices_diverge() -> None:
    left = build_golden_bars("2024_carry")
    right = left.copy()
    right["source"] = "stooq"
    right["close_raw"] = right["close_raw"] * 1.05  # 500 bps blowout everywhere
    report = reconcile_daily_bars(left, right, left_source="golden", right_source="stooq")
    assert not check_p3_source_consistency(report).passed


# ---- P4 --------------------------------------------------------------------


def test_p4_continuity_passes_on_backward_adjusted_split() -> None:
    # A 2:1 split on the event date: raw halves but adjusted stays continuous.
    closes = [
        (date(2024, 1, 2), 100.0),
        (date(2024, 1, 3), 101.0),
        (date(2024, 1, 4), 101.5),  # split date, adjusted already smooth
        (date(2024, 1, 5), 102.0),
    ]
    p4 = check_p4_adjusted_price_continuity(closes, event_dates=[date(2024, 1, 4)])
    assert p4.passed


def test_p4_continuity_flags_unadjusted_split_jump() -> None:
    closes = [
        (date(2024, 1, 2), 100.0),
        (date(2024, 1, 3), 100.0),
        (date(2024, 1, 4), 50.0),  # raw split jump left in the adjusted series
        (date(2024, 1, 5), 50.0),
    ]
    p4 = check_p4_adjusted_price_continuity(closes, event_dates=[date(2024, 1, 4)])
    assert not p4.passed
    assert p4.detail["discontinuities"]


def test_p4_continuity_skips_non_positive_prev_close() -> None:
    # A zero/None-priced prior day (e.g. a suspended listing) is skipped rather
    # than dividing by zero; the surrounding series stays continuous.
    closes = [
        (date(2024, 1, 2), 0.0),
        (date(2024, 1, 3), 100.0),
        (date(2024, 1, 4), 101.0),
    ]
    p4 = check_p4_adjusted_price_continuity(closes, event_dates=[date(2024, 1, 3)])
    assert p4.passed


# ---- P6 --------------------------------------------------------------------


def test_p6_digest_reproducible_across_runs() -> None:
    bars = repo_view(build_golden_bars("2022_hikes"))
    p6 = check_p6_digest_reproducible(
        bars=bars, provider_factory=_core_provider_factory(), initial_cash=50_000.0, runs=3
    )
    assert p6.passed
    assert p6.detail["unique_digests"] == 1


# ---- P10 -------------------------------------------------------------------


def _full_inputs() -> RegimeInputs:
    return RegimeInputs(
        spy_close=100.0,
        spy_ma_10m=90.0,
        pct_sectors_above_200d=0.7,
        hy_oas_percentile=0.3,
        hy_oas_change_3m_bp=-60.0,
        hyg_lqd_z=0.5,
        vix_level=13.0,
        vix_term_inversion_days=0,
        rsp_spy_trend_slope=0.1,
        pct_above_200d=0.7,
        nfci=-0.3,
        nfci_change=-0.1,
        curve_10y_3m=0.5,
        usd_change_3m=0.0,
    )


def test_p10_availability_holds_even_with_stale_pillars() -> None:
    series = [
        (date(2024, 1, 5), _full_inputs()),
        (date(2024, 1, 12), RegimeInputs()),  # every pillar stale -> carry forward
        (date(2024, 1, 19), _full_inputs()),
    ]
    readings = [reading for _, reading in replay(series)]
    p10 = check_p10_state_machine_availability(readings)
    assert p10.passed
    assert p10.detail["stale_periods"] == 1


def test_p10_availability_fails_on_empty_series() -> None:
    assert not check_p10_state_machine_availability([]).passed


# ---- P11 -------------------------------------------------------------------


def test_p11_layer_budget_flags_overlay_breach() -> None:
    breach = check_p11_layer_budget({"core": 0.8, "overlay": 0.15})
    assert not breach.passed
    assert breach.severity == "S1"
    assert "overlay_cap" in cast(list[str], breach.detail["violations"])


def test_p11_layer_budget_flags_leverage() -> None:
    lev = check_p11_layer_budget({"core": 0.8, "satellite": 0.3})
    assert not lev.passed
    assert "leverage" in cast(list[str], lev.detail["violations"])


def test_p11_layer_budget_passes_within_caps() -> None:
    ok = check_p11_layer_budget({"core": 0.7, "satellite": 0.2, "overlay": 0.08})
    assert ok.passed


# ---- Panel -----------------------------------------------------------------


def test_panel_orders_and_reports_blocking_verdict() -> None:
    results = [
        MetricResult("P11", "layer", True, "S1", {}),
        MetricResult("P1", "acct", True, "block", {}),
        MetricResult("P2", "nav", False, "block", {}),
    ]
    panel = build_panel(results)
    assert [r.metric for r in panel.results] == ["P1", "P2", "P11"]
    assert not panel.passed
    assert panel.as_dict()["blocking_failures"] == ["P2"]
    assert "RED" in panel.render_text()


def test_panel_green_when_only_non_blocking_fails() -> None:
    results = [
        MetricResult("P1", "acct", True, "block", {}),
        MetricResult("P11", "layer", False, "S1", {}),
    ]
    panel = build_panel(results)
    assert panel.passed  # S1 failure does not block the panel verdict
    assert "GREEN" in panel.render_text()
    assert len(panel.failures) == 1
