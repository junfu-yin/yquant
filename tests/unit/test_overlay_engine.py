"""WP16 Overlay engine — the 2x leverage-clause executor and the paper book.

These unit tests pin the deterministic pieces the T17/T18 traps assume but do
not exercise directly:

* :mod:`yquant.overlay.leverage` — the universe filter (3x/inverse forbidden,
  only recognised 2x-long admitted), the three-condition open gate, the
  notional-x2 caps, the 60-day review deadline, and the daily book review that
  closes on downgrade (S2), invalidation (S1) or deadline (S3);
* :mod:`yquant.overlay.paper_book` — the shadow-mode tracker that replays
  committee opportunities on paper and emits invalidation/expiry statistics
  (the "纸上机会簿在影子期跑通并出统计" gate, K1').
"""

from datetime import date
from pathlib import Path

import pytest

from yquant.macro.schemas import OpportunityBookEntry
from yquant.overlay import (
    LEVERAGED_2X_SINGLE_CAP,
    LEVERAGED_2X_TOTAL_CAP,
    REVIEW_DEADLINE_DAYS,
    LeverageOpenRequest,
    LeveragePosition,
    PaperEntry,
    classify_2x,
    open_leverage_position,
    review_leverage_positions,
    run_paper_book,
    three_condition_gate,
)
from yquant.risk.state_machine import RegimeState

AS_OF = date(2024, 6, 3)


# ---------------------------------------------------------------- classify ---


def test_classify_2x_partitions_the_universe() -> None:
    assert classify_2x("SSO") == "leveraged_2x_long"
    assert classify_2x("qld") == "leveraged_2x_long"  # case-insensitive
    assert classify_2x(" UGL ") == "leveraged_2x_long"  # trimmed
    assert classify_2x("TQQQ") == "leveraged_3x"
    assert classify_2x("SQQQ") == "inverse"
    assert classify_2x("SPY") == "ordinary"


# ------------------------------------------------------ three-condition gate -


def test_three_condition_gate_all_hold() -> None:
    assert three_condition_gate(
        regime=RegimeState.RISK_ON, above_10m_ma=True, vix_level=15.0
    ) == []


def test_three_condition_gate_names_every_failure() -> None:
    failed = three_condition_gate(
        regime=RegimeState.RISK_OFF, above_10m_ma=False, vix_level=25.0
    )
    assert set(failed) == {"regime_not_risk_on", "below_10m_ma", "vix_not_below_20"}


def test_three_condition_gate_vix_boundary_is_exclusive() -> None:
    # VIX must be strictly below 20; exactly 20 fails.
    assert "vix_not_below_20" in three_condition_gate(
        regime=RegimeState.RISK_ON, above_10m_ma=True, vix_level=20.0
    )
    assert three_condition_gate(
        regime=RegimeState.RISK_ON, above_10m_ma=True, vix_level=19.99
    ) == []


# ----------------------------------------------------------- open executor ---


def _request(ticker: str = "SSO", weight: float = 0.01) -> LeverageOpenRequest:
    return LeverageOpenRequest(
        ticker=ticker,
        weight=weight,
        invalidation_condition="SSO closes below 40",
        as_of=AS_OF,
        above_10m_ma=True,
    )


def test_open_admits_a_clean_2x_long_request() -> None:
    position, rejection = open_leverage_position(
        _request(weight=0.01), regime=RegimeState.RISK_ON, vix_level=15.0
    )
    assert rejection is None
    assert position is not None
    assert position.ticker == "SSO"
    assert position.weight == pytest.approx(0.01)
    # Budget is charged on notional (weight x 2), never face value.
    assert position.notional_weight == pytest.approx(0.02)
    assert position.opened_on == AS_OF
    assert (position.review_by - position.opened_on).days == REVIEW_DEADLINE_DAYS


def test_open_rejects_3x_and_inverse_at_the_universe_filter() -> None:
    _, rej3x = open_leverage_position(
        _request(ticker="TQQQ"), regime=RegimeState.RISK_ON, vix_level=15.0
    )
    assert rej3x is not None and rej3x.rule == "leveraged_3x_forbidden"

    _, rej_inv = open_leverage_position(
        _request(ticker="SQQQ"), regime=RegimeState.RISK_ON, vix_level=15.0
    )
    assert rej_inv is not None and rej_inv.rule == "inverse_forbidden"


def test_open_rejects_ordinary_ticker() -> None:
    _, rejection = open_leverage_position(
        _request(ticker="SPY"), regime=RegimeState.RISK_ON, vix_level=15.0
    )
    assert rejection is not None and rejection.rule == "not_a_2x_long_etf"


def test_open_rejects_unparseable_invalidation() -> None:
    bad = LeverageOpenRequest(
        ticker="SSO",
        weight=0.02,
        invalidation_condition="if the trade stops working",
        as_of=AS_OF,
        above_10m_ma=True,
    )
    _, rejection = open_leverage_position(bad, regime=RegimeState.RISK_ON, vix_level=15.0)
    assert rejection is not None
    assert rejection.rule == "invalidation_not_machine_readable"


def test_open_refuses_outside_risk_on() -> None:
    for regime in (RegimeState.NEUTRAL, RegimeState.RISK_OFF, RegimeState.CRISIS):
        _, rejection = open_leverage_position(
            _request(), regime=regime, vix_level=15.0
        )
        assert rejection is not None
        assert rejection.rule == "open_conditions_unmet"
        assert "regime_not_risk_on" in str(rejection.detail["failed"])


def test_open_enforces_single_name_notional_cap() -> None:
    # weight 0.02 -> notional 0.04 > 0.03 single cap.
    _, rejection = open_leverage_position(
        _request(weight=0.02),
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
    )
    # 0.04 notional breaches the 0.03 single cap.
    assert rejection is not None
    assert rejection.rule == "leveraged_2x_single_cap"
    assert rejection.detail["cap"] == LEVERAGED_2X_SINGLE_CAP


def test_open_enforces_sleeve_total_notional_cap() -> None:
    # A single 0.014 weight -> 0.028 notional is within single cap, but stacked on
    # a sleeve already at 0.03 notional it exceeds the 0.05 total cap.
    position, rejection = open_leverage_position(
        _request(weight=0.014),
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
        sleeve_notional_before=0.03,
    )
    assert position is None
    assert rejection is not None
    assert rejection.rule == "leveraged_2x_total_cap"
    assert rejection.detail["cap"] == LEVERAGED_2X_TOTAL_CAP


def test_open_admits_within_single_cap() -> None:
    # weight 0.015 -> notional 0.03 == single cap (inclusive).
    position, rejection = open_leverage_position(
        _request(weight=0.015), regime=RegimeState.RISK_ON, vix_level=15.0
    )
    assert rejection is None
    assert position is not None
    assert position.notional_weight == pytest.approx(0.03)


# ----------------------------------------------------------- daily review ---


def _position(ticker: str = "SSO", weight: float = 0.015) -> LeveragePosition:
    position, rejection = open_leverage_position(
        LeverageOpenRequest(
            ticker=ticker,
            weight=weight,
            invalidation_condition=f"{ticker} closes below 40",
            as_of=AS_OF,
            above_10m_ma=True,
        ),
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
    )
    assert rejection is None and position is not None
    return position


def test_review_holds_a_healthy_position() -> None:
    pos = _position()
    rows = review_leverage_positions(
        [pos],
        on_date=AS_OF,
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
        metrics={"SSO": 55.0},
    )
    assert len(rows) == 1
    assert rows[0].verdict == "hold"
    assert rows[0].reason is None


def test_review_closes_on_regime_downgrade_first() -> None:
    pos = _position()
    rows = review_leverage_positions(
        [pos],
        on_date=AS_OF,
        regime=RegimeState.RISK_OFF,
        vix_level=15.0,
        metrics={"SSO": 55.0},
    )
    assert rows[0].verdict == "close"
    assert rows[0].reason == "regime_downgrade:RiskOff"


def test_review_closes_on_invalidation_hit() -> None:
    pos = _position()
    rows = review_leverage_positions(
        [pos],
        on_date=AS_OF,
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
        metrics={"SSO": 39.0},  # below 40 -> invalidation fires
    )
    assert rows[0].verdict == "close"
    assert rows[0].reason == "invalidation_hit"


def test_review_closes_on_review_deadline() -> None:
    pos = _position()
    rows = review_leverage_positions(
        [pos],
        on_date=pos.review_by,
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
        metrics={"SSO": 55.0},
    )
    assert rows[0].verdict == "close"
    assert rows[0].reason == "review_deadline"


def test_review_is_ordered_by_ticker() -> None:
    rows = review_leverage_positions(
        [_position("QLD"), _position("SSO"), _position("DDM")],
        on_date=AS_OF,
        regime=RegimeState.RISK_ON,
        vix_level=15.0,
        metrics={},
    )
    assert [r.ticker for r in rows] == ["DDM", "QLD", "SSO"]


def test_review_closes_on_vix_spike() -> None:
    pos = _position()
    rows = review_leverage_positions(
        [pos],
        on_date=AS_OF,
        regime=RegimeState.RISK_ON,
        vix_level=22.0,  # VIX back at/above 20 while still RiskOn
        metrics={"SSO": 55.0},
    )
    assert rows[0].verdict == "close"
    assert rows[0].reason == "vix_not_below_20"
    assert rows[0].as_dict()["reason"] == "vix_not_below_20"


def test_leverage_position_as_dict_is_json_safe() -> None:
    pos = _position()
    payload = pos.as_dict()
    assert payload["ticker"] == "SSO"
    assert payload["opened_on"] == AS_OF.isoformat()
    assert payload["notional_weight"] == pytest.approx(0.03)


# --------------------------------------------------------------- paper book -


def _entry(
    *,
    ticker: str,
    invalidation: str,
    time_limit_days: int = 90,
) -> OpportunityBookEntry:
    return OpportunityBookEntry(
        thesis=f"{ticker} tactical view",
        global_rationale="a global driver with a clear channel to US",
        us_ticker=ticker,
        direction="long",
        entry_condition=f"{ticker} reclaims 50dma at 50",
        invalidation_condition=invalidation,
        weight=0.03,
        time_limit_days=time_limit_days,
        red_team_note="size small",
    )


def test_paper_book_records_invalidation() -> None:
    entry = PaperEntry(
        entry=_entry(ticker="MCHI", invalidation="MCHI closes below 45"),
        entered_on=date(2024, 1, 2),
    )
    sessions = [
        (date(2024, 1, 2), {"MCHI": 50.0}),
        (date(2024, 1, 3), {"MCHI": 48.0}),
        (date(2024, 1, 4), {"MCHI": 44.0}),  # fires here
        (date(2024, 1, 5), {"MCHI": 40.0}),
    ]
    stats = run_paper_book([entry], sessions)
    assert stats.entered == 1
    assert stats.invalidated == 1
    assert stats.expired == 0
    assert stats.still_open == 0
    assert stats.invalidation_rate == pytest.approx(1.0)
    result = stats.results[0]
    assert result.outcome == "invalidated"
    assert result.closed_on == date(2024, 1, 4)
    assert result.holding_days == 2
    assert result.close_reason == "invalidation_hit"


def test_paper_book_records_time_limit_expiry() -> None:
    entry = PaperEntry(
        entry=_entry(ticker="INDA", invalidation="INDA closes below 20", time_limit_days=3),
        entered_on=date(2024, 1, 2),
    )
    sessions = [
        (date(2024, 1, 2), {"INDA": 50.0}),
        (date(2024, 1, 3), {"INDA": 51.0}),
        (date(2024, 1, 5), {"INDA": 52.0}),  # ordinal >= entered + 3 -> expires
        (date(2024, 1, 8), {"INDA": 53.0}),
    ]
    stats = run_paper_book([entry], sessions)
    assert stats.expired == 1
    assert stats.invalidated == 0
    result = stats.results[0]
    assert result.outcome == "expired"
    assert result.close_reason == "time_limit"
    assert result.closed_on == date(2024, 1, 5)


def test_paper_book_records_still_open() -> None:
    entry = PaperEntry(
        entry=_entry(ticker="EWJ", invalidation="EWJ closes below 20", time_limit_days=365),
        entered_on=date(2024, 1, 2),
    )
    sessions = [
        (date(2024, 1, 2), {"EWJ": 60.0}),
        (date(2024, 1, 9), {"EWJ": 62.0}),
    ]
    stats = run_paper_book([entry], sessions)
    assert stats.still_open == 1
    result = stats.results[0]
    assert result.outcome == "open"
    assert result.closed_on is None
    assert result.holding_days == 7


def test_paper_book_ignores_sessions_before_entry() -> None:
    # A pre-entry session that would fire the invalidation must be skipped.
    entry = PaperEntry(
        entry=_entry(ticker="MCHI", invalidation="MCHI closes below 45", time_limit_days=365),
        entered_on=date(2024, 1, 5),
    )
    sessions = [
        (date(2024, 1, 2), {"MCHI": 40.0}),  # before entry -> ignored
        (date(2024, 1, 6), {"MCHI": 55.0}),
    ]
    stats = run_paper_book([entry], sessions)
    assert stats.still_open == 1
    result = stats.results[0]
    assert result.outcome == "open"
    assert result.as_dict()["us_ticker"] == "MCHI"
    assert result.as_dict()["closed_on"] is None


def test_paper_book_aggregates_a_mixed_window() -> None:
    entries = [
        PaperEntry(
            entry=_entry(ticker="MCHI", invalidation="MCHI closes below 45"),
            entered_on=date(2024, 1, 2),
        ),
        PaperEntry(
            entry=_entry(
                ticker="INDA", invalidation="INDA closes below 20", time_limit_days=2
            ),
            entered_on=date(2024, 1, 2),
        ),
        PaperEntry(
            entry=_entry(
                ticker="EWJ", invalidation="EWJ closes below 20", time_limit_days=365
            ),
            entered_on=date(2024, 1, 2),
        ),
    ]
    sessions = [
        (date(2024, 1, 2), {"MCHI": 50.0, "INDA": 50.0, "EWJ": 60.0}),
        (date(2024, 1, 3), {"MCHI": 44.0, "INDA": 50.0, "EWJ": 61.0}),
        (date(2024, 1, 5), {"MCHI": 40.0, "INDA": 55.0, "EWJ": 62.0}),
    ]
    stats = run_paper_book(entries, sessions)
    assert stats.entered == 3
    assert stats.invalidated == 1
    assert stats.expired == 1
    assert stats.still_open == 1
    assert stats.invalidation_rate == pytest.approx(1 / 3)
    # Only closed positions count toward the mean holding period.
    assert stats.mean_holding_days > 0.0


def test_paper_book_empty_is_well_defined() -> None:
    stats = run_paper_book([], [])
    assert stats.entered == 0
    assert stats.invalidation_rate == 0.0
    assert stats.mean_holding_days == 0.0
    assert stats.as_dict()["results"] == []


def test_paper_book_sorts_unordered_sessions() -> None:
    # Sessions supplied out of order must be replayed chronologically.
    entry = PaperEntry(
        entry=_entry(ticker="MCHI", invalidation="MCHI closes below 45"),
        entered_on=date(2024, 1, 2),
    )
    sessions = [
        (date(2024, 1, 4), {"MCHI": 44.0}),
        (date(2024, 1, 2), {"MCHI": 50.0}),
        (date(2024, 1, 3), {"MCHI": 48.0}),
    ]
    stats = run_paper_book([entry], sessions)
    assert stats.results[0].closed_on == date(2024, 1, 4)


# ------------------------------------------------------------- demo + cli ----


def test_demo_paper_book_exercises_every_outcome() -> None:
    from yquant.overlay.demo import build_demo_paper_book

    stats = build_demo_paper_book()
    assert stats.entered == 3
    assert stats.invalidated == 1  # MCHI (S1)
    assert stats.expired == 1  # INDA (S3, time limit)
    assert stats.still_open == 1  # EWJ
    by_ticker = {r.us_ticker: r for r in stats.results}
    assert by_ticker["MCHI"].outcome == "invalidated"
    assert by_ticker["MCHI"].closed_on == date(2024, 1, 4)
    assert by_ticker["INDA"].outcome == "expired"
    assert by_ticker["EWJ"].outcome == "open"


def test_overlay_paper_book_cli_prints_statistics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from yquant.cli import main

    assert main(["overlay", "paper-book"]) == 0
    out = capsys.readouterr().out
    assert "overlay paper-book" in out
    assert "entered=3" in out
    assert "invalidated=1" in out
    assert "MCHI: invalidated" in out


def test_overlay_paper_book_cli_writes_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from yquant.cli import main

    out_path = tmp_path / "paper_book.json"
    assert main(["overlay", "paper-book", "--output", str(out_path)]) == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["entered"] == 3
    assert payload["invalidated"] == 1
    assert len(payload["results"]) == 3
    assert "paper_book_artifact" in capsys.readouterr().out
