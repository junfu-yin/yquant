from datetime import date
from pathlib import Path

import pytest

from yquant.config import ConfigError, load_config


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


def test_config_rejects_invalid_timezone(tmp_path: Path) -> None:
    text = Path("config.example.toml").read_text(encoding="utf-8")
    path = tmp_path / "bad-timezone.toml"
    path.write_text(
        text.replace('timezone = "America/New_York"', 'timezone = "Mars/Olympus"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="timezone"):
        load_config(path)


def test_config_rejects_non_finite_cost(tmp_path: Path) -> None:
    text = Path("config.example.toml").read_text(encoding="utf-8")
    path = tmp_path / "bad-cost.toml"
    path.write_text(
        text.replace("commission_per_trade_usd = 9.5", "commission_per_trade_usd = nan"),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_config(path)
