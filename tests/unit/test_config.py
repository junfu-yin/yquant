from datetime import date

from yquant.config import load_config


def test_load_example_config() -> None:
    cfg = load_config("config.example.toml")

    assert cfg.runtime.timezone == "Asia/Shanghai"
    assert cfg.data.markets == ("us", "hk")
    assert cfg.data.primary_source == "yfinance"
    assert cfg.data.backup_sources == ("akshare", "stooq")
    assert cfg.data.history_start == date(2010, 1, 1)
    assert cfg.llm.daily_budget_cny == 2.0
    assert cfg.risk.single_position_limit == 0.15

