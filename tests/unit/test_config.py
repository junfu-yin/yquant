from datetime import date

from yquant.config import load_config


def test_load_example_config() -> None:
    cfg = load_config("config.example.toml")

    assert cfg.runtime.timezone == "America/New_York"
    assert cfg.data.markets == ("us",)
    assert cfg.data.primary_source == "yfinance"
    assert cfg.data.backup_sources == ("nasdaq",)
    assert cfg.data.history_start == date(2010, 1, 1)
    assert cfg.llm.daily_budget_alert_usd is None
    assert cfg.risk.core_budget == 0.75
    assert cfg.risk.satellite_budget == 0.15
    assert cfg.risk.overlay_budget == 0.10
    assert cfg.risk.single_position_limit == 0.15
    assert cfg.risk.overlay_single_position_limit == 0.05
    assert cfg.risk.leveraged_etf_total_limit == 0.05
    assert cfg.risk.leveraged_etf_single_limit == 0.03
