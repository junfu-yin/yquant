"""T7 dual-engine parity (06 §2): backtest vs PaperBroker ≤2bps daily / ≤20bps cumulative.

Because the paper path reuses the backtest's constraint core, parity is exact
(0 bps) on every window — a non-zero drift would signal an accounting bug, which
is precisely what the plan wants T7 to catch. We assert both the bps caps and the
stronger property they imply here: byte-identical run digests.
"""

from datetime import date

import pytest

from yquant.datasrc.bars import repo_view
from yquant.paper.parity import parity_report, shadow_reconciliation
from yquant.qa.golden import GOLDEN_WINDOWS, build_golden_bars
from yquant.strategies.base import TargetPortfolio

_PAPER_CASH = 50_000.0


def _three_layer_factory() -> object:
    def factory():  # type: ignore[no-untyped-def]
        placed = {"done": False}

        def provider(day: date, closes: dict[str, float]) -> TargetPortfolio | None:
            if placed["done"] or not closes:
                return None
            placed["done"] = True
            return TargetPortfolio(
                as_of=day,
                weights={"SPY": 0.5, "TLT": 0.2, "GLD": 0.1, "QQQ": 0.08},
                layers={"SPY": "core", "TLT": "core", "GLD": "satellite", "QQQ": "overlay"},
                cash_weight=0.12,
            )

        return provider

    return factory


@pytest.mark.parametrize("window", [w.key for w in GOLDEN_WINDOWS])
def test_t7_parity_is_exact_on_every_golden_window(window: str) -> None:
    bars = repo_view(build_golden_bars(window), adjust="adjusted")
    report = parity_report(
        bars=bars, provider_factory=_three_layer_factory(), initial_cash=_PAPER_CASH
    )

    assert report.passed
    assert report.max_daily_bps <= report.daily_cap_bps
    assert report.cumulative_bps <= report.cumulative_cap_bps
    # The shared core makes parity exact, not merely within tolerance.
    assert report.max_daily_bps == 0.0
    assert report.cumulative_bps == 0.0
    assert report.backtest_digest == report.paper_digest


def test_shadow_report_meets_l1_gate_on_covid_window() -> None:
    """08 §1 L1 shadow: ≥20 sessions of parity with zero reconciliation breaches."""

    bars = repo_view(build_golden_bars("2020_covid"), adjust="adjusted")
    report = shadow_reconciliation(
        bars=bars,
        provider_factory=_three_layer_factory(),
        initial_cash=_PAPER_CASH,
        min_sessions=20,
    )

    assert report.passed
    assert report.meets_min_sessions
    assert report.reconciliation_breaches == 0
    assert report.parity.sessions >= 20
