"""A-share price-limit rules.

The final rule table must be verified in WP0 AS-6. This module still gives the
rest of the code a typed object instead of scattering percentages across the
codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MAIN_BOARD_LIMIT = Decimal("0.10")
ST_LIMIT = Decimal("0.05")
CHINEXT_REGISTRATION_REFORM = date(2020, 8, 24)
STAR_MARKET_OPEN = date(2019, 7, 22)
BSE_OPEN = date(2021, 11, 15)


@dataclass(frozen=True)
class PriceLimitRule:
    """Daily price-limit rule.

    `None` means the corresponding side has no price limit. Main-board IPO day
    can be asymmetric, so callers should prefer this object over a single pct.
    """

    up_pct: Decimal | None
    down_pct: Decimal | None
    reason: str

    @property
    def symmetric_pct(self) -> Decimal | None:
        if self.up_pct != self.down_pct:
            raise ValueError("price-limit rule is asymmetric")
        return self.up_pct


def price_limit_rule(
    symbol: str,
    board: str,
    day: date,
    *,
    is_st: bool,
    list_date: date | None = None,
    trading_days_since_listing: int | None = None,
) -> PriceLimitRule:
    """Return the A-share price-limit rule for a trading day.

    `trading_days_since_listing` is optional because M1 owns the trading
    calendar. When it is not provided, this function does not guess "first five
    trading days" from calendar days.
    """

    del symbol  # Reserved for future symbol-level exceptions.
    normalized_board = _normalize_board(board)

    if is_st:
        return PriceLimitRule(ST_LIMIT, ST_LIMIT, "st_or_star_st")

    if _is_unlimited_new_listing(
        normalized_board, day, list_date, trading_days_since_listing
    ):
        return PriceLimitRule(None, None, "registration_based_first_five_trading_days")

    if _is_main_board_ipo_day(normalized_board, list_date, trading_days_since_listing):
        return PriceLimitRule(Decimal("0.44"), Decimal("0.36"), "main_board_ipo_first_day")

    if normalized_board == "chinext":
        if day >= CHINEXT_REGISTRATION_REFORM:
            return PriceLimitRule(Decimal("0.20"), Decimal("0.20"), "chinext_after_2020_08_24")
        return PriceLimitRule(MAIN_BOARD_LIMIT, MAIN_BOARD_LIMIT, "chinext_before_2020_08_24")

    if normalized_board == "star":
        return PriceLimitRule(Decimal("0.20"), Decimal("0.20"), "star_market")

    if normalized_board == "bse":
        return PriceLimitRule(Decimal("0.30"), Decimal("0.30"), "beijing_stock_exchange")

    return PriceLimitRule(MAIN_BOARD_LIMIT, MAIN_BOARD_LIMIT, "main_board")


def limit_rule(
    symbol: str,
    board: str,
    day: date,
    is_st: bool,
    list_date: date | None,
) -> Decimal | None:
    """Compatibility wrapper matching the current spec's single-pct signature."""

    return price_limit_rule(
        symbol=symbol,
        board=board,
        day=day,
        is_st=is_st,
        list_date=list_date,
    ).symmetric_pct


def _normalize_board(board: str) -> str:
    value = board.strip().lower()
    aliases = {
        "main": "main",
        "main_board": "main",
        "sh_main": "main",
        "sz_main": "main",
        "sse": "main",
        "szse": "main",
        "chinext": "chinext",
        "gem": "chinext",
        "star": "star",
        "sci_tech": "star",
        "bse": "bse",
        "bjse": "bse",
    }
    return aliases.get(value, value)


def _is_unlimited_new_listing(
    board: str,
    day: date,
    list_date: date | None,
    trading_days_since_listing: int | None,
) -> bool:
    if list_date is None or trading_days_since_listing is None:
        return False
    if trading_days_since_listing < 1 or trading_days_since_listing > 5:
        return False
    if board == "star" and day >= STAR_MARKET_OPEN:
        return True
    return (
        board == "chinext"
        and day >= CHINEXT_REGISTRATION_REFORM
        and list_date >= CHINEXT_REGISTRATION_REFORM
    )


def _is_main_board_ipo_day(
    board: str,
    list_date: date | None,
    trading_days_since_listing: int | None,
) -> bool:
    return board == "main" and list_date is not None and trading_days_since_listing == 1

