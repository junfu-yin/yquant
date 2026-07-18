"""EDGAR filing taxonomy + non-LLM structured parsers (03 §5.4, ADR-21).

Two of the M4 inputs are *deterministic by contract* and must not touch an LLM:

* **8-K item-code direct read** — the SEC 8-K form encodes its meaning in item
  numbers (2.02 = results of operations, 5.02 = officer departure, ...). We map
  those codes straight to an event category, a base severity and a base
  direction. No model is asked "what kind of filing is this"; the form already
  says so.
* **Form 4 structured parse** — insider transactions arrive as XML with typed
  transaction codes (``P`` open-market purchase, ``S`` sale, ``A`` grant, ...).
  Direction and magnitude come from the structured fields, never from prose.

A rule-based *pre-classifier* refines the free-text items (7.01 Reg-FD / 8.01
Other Events press releases) with a small, auditable keyword table — buybacks,
dividends, guidance, litigation, investigations — because those business events
ride on otherwise-generic item codes. The LLM (which lands later) only ever
*summarises* an already-classified filing; it never gets a vote on the category.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

EventType = Literal[
    "业绩财报",
    "指引调整",
    "回购增持",
    "内部人交易",
    "并购重组",
    "重大合同",
    "监管调查",
    "诉讼仲裁",
    "股权融资/增发",
    "分红拆股",
    "人事变动",
    "异动提示",
    "其他",
]
Direction = Literal["利多", "利空", "中性", "不确定"]


@dataclass(frozen=True)
class ItemSpec:
    """The deterministic classification a single 8-K item code implies."""

    code: str
    label: str
    event_type: EventType
    severity: int
    direction: Direction


# Official 8-K item codes (ADR-21 "官方语汇"). Severity/direction are the base
# read; the free-text refiner can only *raise* salience, never invent a category.
EIGHT_K_ITEMS: dict[str, ItemSpec] = {
    "1.01": ItemSpec("1.01", "Material Definitive Agreement", "重大合同", 3, "中性"),
    "1.02": ItemSpec("1.02", "Termination of Material Agreement", "重大合同", 3, "利空"),
    "1.05": ItemSpec("1.05", "Material Cybersecurity Incident", "监管调查", 4, "利空"),
    "2.01": ItemSpec("2.01", "Acquisition or Disposition", "并购重组", 4, "中性"),
    "2.02": ItemSpec("2.02", "Results of Operations", "业绩财报", 3, "中性"),
    "2.03": ItemSpec("2.03", "Direct Financial Obligation", "股权融资/增发", 3, "中性"),
    "2.04": ItemSpec("2.04", "Triggering Events on Obligation", "异动提示", 4, "利空"),
    "2.05": ItemSpec("2.05", "Exit or Disposal Costs", "异动提示", 3, "利空"),
    "2.06": ItemSpec("2.06", "Material Impairments", "业绩财报", 4, "利空"),
    "3.01": ItemSpec("3.01", "Delisting / Listing Failure", "异动提示", 5, "利空"),
    "3.02": ItemSpec("3.02", "Unregistered Equity Sales", "股权融资/增发", 3, "利空"),
    "3.03": ItemSpec("3.03", "Modification of Holder Rights", "股权融资/增发", 3, "中性"),
    "4.01": ItemSpec("4.01", "Change in Accountant", "人事变动", 3, "中性"),
    "4.02": ItemSpec("4.02", "Non-Reliance on Financials", "监管调查", 5, "利空"),
    "5.01": ItemSpec("5.01", "Change in Control", "并购重组", 4, "中性"),
    "5.02": ItemSpec("5.02", "Officer/Director Change", "人事变动", 3, "中性"),
    "5.03": ItemSpec("5.03", "Bylaw Amendments", "其他", 2, "中性"),
    "5.07": ItemSpec("5.07", "Shareholder Vote Results", "其他", 2, "中性"),
    "7.01": ItemSpec("7.01", "Regulation FD Disclosure", "异动提示", 2, "中性"),
    "8.01": ItemSpec("8.01", "Other Events", "其他", 2, "中性"),
}


@dataclass(frozen=True)
class KeywordRule:
    """A free-text refinement rule for press-release style items (7.01 / 8.01)."""

    keywords: tuple[str, ...]
    event_type: EventType
    severity: int
    direction: Direction


# Applied only to press-release items; order = priority (first match wins).
_KEYWORD_RULES: tuple[KeywordRule, ...] = (
    KeywordRule(("share repurchase", "buyback", "repurchase program"), "回购增持", 3, "利多"),
    KeywordRule(("increases quarterly dividend", "raises dividend", "dividend increase"),
                "分红拆股", 3, "利多"),
    KeywordRule(("suspends dividend", "cuts dividend", "dividend suspension"),
                "分红拆股", 4, "利空"),
    KeywordRule(("stock split", "forward split"), "分红拆股", 2, "中性"),
    KeywordRule(("raises full-year guidance", "raises guidance", "increases guidance"),
                "指引调整", 3, "利多"),
    KeywordRule(("lowers guidance", "cuts guidance", "reduces guidance", "withdraws guidance"),
                "指引调整", 4, "利空"),
    KeywordRule(("class action", "lawsuit", "litigation", "settlement of"),
                "诉讼仲裁", 3, "利空"),
    KeywordRule(("sec investigation", "subpoena", "formal investigation", "wells notice"),
                "监管调查", 4, "利空"),
)


def classify_8k(item_codes: list[str], *, body: str = "") -> ItemSpec:
    """Pick the salient classification for an 8-K from its item codes.

    Multiple items can appear on one 8-K; we take the highest base severity
    (ties broken by declaration order). Press-release items (7.01/8.01) are then
    refined against ``body`` with the keyword table, which may override the
    generic "异动提示 / 其他" read with a concrete business category.
    """

    known = [EIGHT_K_ITEMS[c] for c in item_codes if c in EIGHT_K_ITEMS]
    if not known:
        raise KeyError(f"no known 8-K item code in {item_codes!r}")

    spec = max(known, key=lambda s: (s.severity, -known.index(s)))
    if spec.code in {"7.01", "8.01"} and body:
        refined = _refine_press_release(body)
        if refined is not None:
            return refined
    return spec


def _refine_press_release(body: str) -> ItemSpec | None:
    lowered = body.lower()
    for rule in _KEYWORD_RULES:
        if any(keyword in lowered for keyword in rule.keywords):
            return ItemSpec(
                code="refined",
                label=f"press release: {rule.event_type}",
                event_type=rule.event_type,
                severity=rule.severity,
                direction=rule.direction,
            )
    return None


# Form 4 transaction codes we treat structurally (SEC Table I/II codes).
# Acquisitions lift the read bullish, dispositions bearish; open-market
# purchases (P) are the strongest insider signal, routine grants (A) the weakest.
_ACQUISITION_CODES = {"P", "A", "M", "C", "G"}
_DISPOSITION_CODES = {"S", "D", "F"}


@dataclass(frozen=True)
class Form4Transaction:
    """One structured Form 4 non-derivative transaction line."""

    transaction_code: str
    shares: float
    price_per_share: float

    @property
    def value_usd(self) -> float:
        return self.shares * self.price_per_share

    @property
    def is_acquisition(self) -> bool:
        return self.transaction_code.upper() in _ACQUISITION_CODES


@dataclass(frozen=True)
class Form4Filing:
    """A parsed Form 4: insider identity + typed transactions (no LLM, ADR-21)."""

    symbol: str
    insider_name: str
    insider_title: str
    filed_at: date
    transactions: list[Form4Transaction] = field(default_factory=list)
    source_url: str = ""

    def net_shares(self) -> float:
        return sum(
            (t.shares if t.is_acquisition else -t.shares) for t in self.transactions
        )

    def gross_value(self) -> float:
        return sum(t.value_usd for t in self.transactions)


def parse_form4(record: dict[str, object]) -> Form4Filing:
    """Build a :class:`Form4Filing` from a structured EDGAR record (non-LLM).

    ``record`` mirrors the fields EDGAR's Form 4 XML exposes; we validate types
    and transaction codes here so a malformed filing is rejected at parse time
    rather than silently mis-scored downstream.
    """

    raw_txns = record.get("transactions", [])
    if not isinstance(raw_txns, list):
        raise TypeError("Form 4 record 'transactions' must be a list")

    transactions: list[Form4Transaction] = []
    for raw in raw_txns:
        if not isinstance(raw, dict):
            raise TypeError("each Form 4 transaction must be a mapping")
        code = str(raw["transaction_code"]).upper()
        known = _ACQUISITION_CODES | _DISPOSITION_CODES
        if code not in known:
            raise ValueError(f"unknown Form 4 transaction code {code!r}")
        shares = float(raw["shares"])
        price_per_share = float(raw["price_per_share"])
        if not math.isfinite(shares) or shares <= 0:
            raise ValueError("Form 4 transaction shares must be finite and positive")
        if not math.isfinite(price_per_share) or price_per_share < 0:
            raise ValueError(
                "Form 4 transaction price_per_share must be finite and non-negative"
            )
        transactions.append(
            Form4Transaction(
                transaction_code=code,
                shares=shares,
                price_per_share=price_per_share,
            )
        )

    filed_raw = record["filed_at"]
    filed_at = filed_raw if isinstance(filed_raw, date) else date.fromisoformat(str(filed_raw))
    return Form4Filing(
        symbol=str(record["symbol"]),
        insider_name=str(record.get("insider_name", "")),
        insider_title=str(record.get("insider_title", "")),
        filed_at=filed_at,
        transactions=transactions,
        source_url=str(record.get("source_url", "")),
    )


def left_truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Left-truncate ``text`` to the last ``max_chars`` characters (03 §5.4).

    Filings put the material discussion near the end (exhibits/boilerplate lead);
    keeping the *tail* preserves the requirement segments the card is built from.
    Returns the (possibly truncated) text and whether truncation happened.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return text, False
    return text[-max_chars:], True
