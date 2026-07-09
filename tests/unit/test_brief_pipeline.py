"""Unit tests for the M4 EDGAR pipeline: 8-K classification + Form 4 + cards (WP4)."""

from __future__ import annotations

from datetime import date

import pytest

from yquant.brief.eval import build_eval_corpus, evaluate_corpus, run_eval
from yquant.brief.filings import (
    EIGHT_K_ITEMS,
    classify_8k,
    left_truncate,
    parse_form4,
)
from yquant.brief.pipeline import (
    EightKFiling,
    NumericVerificationError,
    build_8k_card,
    build_form4_card,
)


def test_classify_8k_reads_item_code_directly() -> None:
    spec = classify_8k(["2.02"])
    assert spec.event_type == "业绩财报"
    assert spec.code == "2.02"


def test_classify_8k_picks_highest_severity_item() -> None:
    # 3.01 (delisting, sev 5) dominates 7.01 (Reg-FD, sev 2).
    spec = classify_8k(["7.01", "3.01"])
    assert spec.code == "3.01"
    assert spec.severity == 5


def test_classify_8k_unknown_code_raises() -> None:
    with pytest.raises(KeyError):
        classify_8k(["99.99"])


def test_classify_8k_press_release_refines_to_buyback() -> None:
    spec = classify_8k(["8.01"], body="The board approved a new share repurchase program.")
    assert spec.event_type == "回购增持"
    assert spec.direction == "利多"


def test_classify_8k_press_release_refines_to_dividend_cut() -> None:
    spec = classify_8k(["8.01"], body="The company suspends dividend payments indefinitely.")
    assert spec.event_type == "分红拆股"
    assert spec.direction == "利空"
    assert spec.severity == 4


def test_left_truncate_keeps_tail() -> None:
    text, truncated = left_truncate("abcdef", 3)
    assert text == "def"
    assert truncated is True


def test_left_truncate_short_text_untouched() -> None:
    text, truncated = left_truncate("abc", 10)
    assert text == "abc"
    assert truncated is False


def test_left_truncate_rejects_nonpositive_budget() -> None:
    with pytest.raises(ValueError):
        left_truncate("abc", 0)


def test_all_item_specs_have_valid_severity() -> None:
    for spec in EIGHT_K_ITEMS.values():
        assert 1 <= spec.severity <= 5
        assert spec.direction in {"利多", "利空", "中性", "不确定"}


def test_build_8k_card_verifies_numbers_and_classifies() -> None:
    filing = EightKFiling(
        symbol="AAPL",
        item_codes=["2.02"],
        filed_at=date(2024, 1, 31),
        body="The company reported net revenue of $1,200 million, up 10.00% year over year.",
        source_url="https://www.sec.gov/edgar/AAPL/8-K/1",
        key_numbers=["$1,200 million", "10.00%"],
    )
    card = build_8k_card(filing)
    assert card.event_type == "业绩财报"
    assert card.market == "us"
    assert card.key_numbers == ["$1,200 million", "10.00%"]
    assert card.input_truncated is False


def test_build_8k_card_rejects_fabricated_number() -> None:
    filing = EightKFiling(
        symbol="AAPL",
        item_codes=["2.02"],
        filed_at=date(2024, 1, 31),
        body="The company reported net revenue of $1,200 million.",
        source_url="https://www.sec.gov/edgar/AAPL/8-K/2",
        key_numbers=["$9,999 million"],
    )
    with pytest.raises(NumericVerificationError) as exc:
        build_8k_card(filing)
    assert "$9,999 million" in exc.value.unverified


def test_build_8k_card_marks_truncation() -> None:
    body = "x" * 100 + " net revenue of $1,200 million."
    filing = EightKFiling(
        symbol="MSFT",
        item_codes=["2.02"],
        filed_at=date(2024, 1, 31),
        body=body,
        source_url="https://www.sec.gov/edgar/MSFT/8-K/3",
        key_numbers=["$1,200 million"],
    )
    card = build_8k_card(filing, max_input_chars=40)
    assert card.input_truncated is True


def test_parse_form4_computes_net_shares_and_value() -> None:
    filing = parse_form4(
        {
            "symbol": "NVDA",
            "insider_name": "Jane Doe",
            "insider_title": "CFO",
            "filed_at": "2024-02-15",
            "source_url": "https://www.sec.gov/edgar/NVDA/4/1",
            "transactions": [
                {"transaction_code": "P", "shares": 1000, "price_per_share": 50.0},
                {"transaction_code": "S", "shares": 200, "price_per_share": 55.0},
            ],
        }
    )
    assert filing.net_shares() == pytest.approx(800.0)
    assert filing.gross_value() == pytest.approx(1000 * 50.0 + 200 * 55.0)


def test_parse_form4_rejects_unknown_transaction_code() -> None:
    with pytest.raises(ValueError):
        parse_form4(
            {
                "symbol": "NVDA",
                "filed_at": "2024-02-15",
                "transactions": [
                    {"transaction_code": "Z", "shares": 1, "price_per_share": 1.0}
                ],
            }
        )


def test_parse_form4_rejects_non_list_transactions() -> None:
    with pytest.raises(TypeError):
        parse_form4({"symbol": "NVDA", "filed_at": "2024-02-15", "transactions": {}})


def test_build_form4_card_bullish_on_net_purchase() -> None:
    filing = parse_form4(
        {
            "symbol": "TSLA",
            "insider_name": "Elon",
            "insider_title": "CEO",
            "filed_at": date(2024, 3, 1),
            "source_url": "https://www.sec.gov/edgar/TSLA/4/9",
            "transactions": [
                {"transaction_code": "P", "shares": 100000, "price_per_share": 200.0}
            ],
        }
    )
    card = build_form4_card(filing)
    assert card.event_type == "内部人交易"
    assert card.direction == "利多"
    # $20M gross -> top severity.
    assert card.severity == 5


def test_build_form4_card_bearish_on_net_sale() -> None:
    filing = parse_form4(
        {
            "symbol": "XOM",
            "insider_name": "Officer",
            "insider_title": "VP",
            "filed_at": date(2024, 3, 1),
            "source_url": "https://www.sec.gov/edgar/XOM/4/2",
            "transactions": [
                {"transaction_code": "S", "shares": 1500, "price_per_share": 100.0}
            ],
        }
    )
    card = build_form4_card(filing)
    assert card.direction == "利空"
    # $150k gross -> severity 3.
    assert card.severity == 3


def test_eval_corpus_is_120_with_traps() -> None:
    corpus = build_eval_corpus()
    assert len(corpus) == 120
    assert sum(1 for s in corpus if s.is_trap) == 18


def test_eval_corpus_passes_all_thresholds() -> None:
    metrics = run_eval()
    assert metrics.total == 120
    assert metrics.classification_accuracy >= 0.85
    assert metrics.severity_within_one >= 0.85
    assert metrics.severity_high_recall >= 0.95
    assert metrics.direction_accuracy >= 0.80
    assert metrics.trap_miss_count == 0
    assert metrics.passed is True


def test_eval_metrics_as_dict_is_json_safe() -> None:
    metrics = run_eval()
    payload = metrics.as_dict()
    assert payload["passed"] is True
    assert payload["trap_miss_count"] == 0
    assert isinstance(payload["misclassified"], list)


def test_evaluate_corpus_counts_trap_miss() -> None:
    # A trap whose "fabricated" number is actually present would slip the gate.
    corpus = build_eval_corpus()
    leaked = [s for s in corpus if not s.is_trap][:1]
    # Re-tag a clean sample as a trap without changing its (verifiable) numbers.
    from dataclasses import replace

    leaked_trap = replace(leaked[0], is_trap=True)
    metrics = evaluate_corpus([leaked_trap])
    assert metrics.trap_miss_count == 1
    assert metrics.passed is False
