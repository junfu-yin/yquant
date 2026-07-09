"""Configuration loading for yquant.

The loader intentionally keeps secrets out of config files. Config contains the
environment variable names, while the actual secret values stay in the runtime
environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


class ConfigError(ValueError):
    """Raised when a config file is missing or invalid."""


@dataclass(frozen=True)
class RuntimeConfig:
    timezone: str
    data_dir: Path
    sqlite_path: Path
    parquet_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class DataConfig:
    markets: tuple[str, ...]
    primary_source: str
    backup_sources: tuple[str, ...]
    history_start: date


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    base_url: str
    model: str
    api_key_env: str
    # ADR-27: the daily budget is no longer a hard cap / circuit breaker; it is an
    # optional soft alert threshold for the usage meter. None means no threshold
    # (spend is still accounted in the llm_usage table regardless).
    daily_budget_alert_usd: float | None
    timeout_seconds: int
    max_input_chars: int


@dataclass(frozen=True)
class RiskConfig:
    core_budget: float
    satellite_budget: float
    overlay_budget: float
    single_position_limit: float
    overlay_single_position_limit: float
    leveraged_etf_total_limit: float
    leveraged_etf_single_limit: float
    industry_position_limit: float
    drawdown_warning: float
    drawdown_strong_warning: float
    cooldown_loss_count: int
    cooldown_trading_days: int


@dataclass(frozen=True)
class FeishuConfig:
    webhook_env: str


@dataclass(frozen=True)
class NotificationConfig:
    feishu: FeishuConfig


@dataclass(frozen=True)
class ScheduleConfig:
    """Optional [schedule] section driving the unattended M1 daemon.

    A ``*_cron`` set to ``None`` means that job is not scheduled. Cron strings
    are standard 5-field expressions interpreted in the runtime timezone.
    """

    symbols: tuple[str, ...] = ()
    history_days: int = 5
    update_cron: str | None = None
    freshness_cron: str | None = None
    reconcile_cron: str | None = None
    regime_cron: str | None = None
    reconcile_sample_size: int | None = None
    reconcile_seed: int | None = None
    minutes_after_close: int = 45
    calendar: str = "NYSE"


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig
    data: DataConfig
    llm: LLMConfig
    risk: RiskConfig
    notification: NotificationConfig
    schedule: ScheduleConfig


def load_config(path: str | Path = "config.example.toml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"config file does not exist: {config_path}")

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    try:
        runtime = _runtime_config(raw["runtime"])
        data = _data_config(raw["data"])
        llm = _llm_config(raw["llm"])
        risk = _risk_config(raw["risk"])
        notification = _notification_config(raw["notification"])
        schedule = _schedule_config(raw.get("schedule"))
    except KeyError as exc:
        raise ConfigError(f"missing config section or key: {exc}") from exc
    except TypeError as exc:
        raise ConfigError(f"invalid config value type: {exc}") from exc

    return AppConfig(
        runtime=runtime,
        data=data,
        llm=llm,
        risk=risk,
        notification=notification,
        schedule=schedule,
    )


def _runtime_config(raw: dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        timezone=str(raw["timezone"]),
        data_dir=Path(raw["data_dir"]),
        sqlite_path=Path(raw["sqlite_path"]),
        parquet_dir=Path(raw["parquet_dir"]),
        log_dir=Path(raw["log_dir"]),
    )


def _data_config(raw: dict[str, Any]) -> DataConfig:
    markets = tuple(str(item).strip().lower() for item in raw["markets"])
    for market in markets:
        if market != "us":
            raise ConfigError(f"data.markets only supports 'us' in v3.1a, got: {market!r}")
    if not markets:
        raise ConfigError("data.markets must not be empty")
    return DataConfig(
        markets=markets,
        primary_source=str(raw["primary_source"]),
        backup_sources=tuple(str(item) for item in raw["backup_sources"]),
        history_start=date.fromisoformat(str(raw["history_start"])),
    )


def _llm_config(raw: dict[str, Any]) -> LLMConfig:
    timeout = int(raw["timeout_seconds"])
    max_input_chars = int(raw["max_input_chars"])
    # ADR-27: no hard budget cap. An optional soft alert threshold is allowed;
    # absent or null means the usage meter simply accounts spend with no alert.
    raw_alert = raw.get("daily_budget_alert_usd")
    daily_budget_alert = float(raw_alert) if raw_alert is not None else None
    if daily_budget_alert is not None and daily_budget_alert <= 0:
        raise ConfigError("llm.daily_budget_alert_usd must be positive when set")
    if timeout <= 0:
        raise ConfigError("llm.timeout_seconds must be positive")
    if max_input_chars <= 0:
        raise ConfigError("llm.max_input_chars must be positive")

    return LLMConfig(
        provider=str(raw["provider"]),
        base_url=str(raw["base_url"]),
        model=str(raw["model"]),
        api_key_env=str(raw["api_key_env"]),
        daily_budget_alert_usd=daily_budget_alert,
        timeout_seconds=timeout,
        max_input_chars=max_input_chars,
    )


def _risk_config(raw: dict[str, Any]) -> RiskConfig:
    cfg = RiskConfig(
        core_budget=float(raw["core_budget"]),
        satellite_budget=float(raw["satellite_budget"]),
        overlay_budget=float(raw["overlay_budget"]),
        single_position_limit=float(raw["single_position_limit"]),
        overlay_single_position_limit=float(raw["overlay_single_position_limit"]),
        leveraged_etf_total_limit=float(raw["leveraged_etf_total_limit"]),
        leveraged_etf_single_limit=float(raw["leveraged_etf_single_limit"]),
        industry_position_limit=float(raw["industry_position_limit"]),
        drawdown_warning=float(raw["drawdown_warning"]),
        drawdown_strong_warning=float(raw["drawdown_strong_warning"]),
        cooldown_loss_count=int(raw["cooldown_loss_count"]),
        cooldown_trading_days=int(raw["cooldown_trading_days"]),
    )
    _require_ratio("risk.core_budget", cfg.core_budget)
    _require_ratio("risk.satellite_budget", cfg.satellite_budget)
    _require_ratio("risk.overlay_budget", cfg.overlay_budget)
    if abs((cfg.core_budget + cfg.satellite_budget + cfg.overlay_budget) - 1.0) > 1e-9:
        raise ConfigError("risk core/satellite/overlay budgets must sum to 1")
    _require_ratio("risk.single_position_limit", cfg.single_position_limit)
    _require_ratio("risk.overlay_single_position_limit", cfg.overlay_single_position_limit)
    _require_ratio("risk.leveraged_etf_total_limit", cfg.leveraged_etf_total_limit)
    _require_ratio("risk.leveraged_etf_single_limit", cfg.leveraged_etf_single_limit)
    _require_ratio("risk.industry_position_limit", cfg.industry_position_limit)
    _require_ratio("risk.drawdown_warning", cfg.drawdown_warning)
    _require_ratio("risk.drawdown_strong_warning", cfg.drawdown_strong_warning)
    if cfg.cooldown_loss_count <= 0:
        raise ConfigError("risk.cooldown_loss_count must be positive")
    if cfg.cooldown_trading_days <= 0:
        raise ConfigError("risk.cooldown_trading_days must be positive")
    return cfg


def _notification_config(raw: dict[str, Any]) -> NotificationConfig:
    return NotificationConfig(feishu=FeishuConfig(webhook_env=str(raw["feishu"]["webhook_env"])))


def _schedule_config(raw: dict[str, Any] | None) -> ScheduleConfig:
    if not raw:
        return ScheduleConfig()

    symbols = tuple(
        str(item).strip().upper() for item in raw.get("symbols", ()) if str(item).strip()
    )
    history_days = int(raw.get("history_days", 5))
    if history_days < 0:
        raise ConfigError("schedule.history_days must be non-negative")

    sample_size = raw.get("reconcile_sample_size")
    if sample_size is not None:
        sample_size = int(sample_size)
        if sample_size <= 0:
            raise ConfigError("schedule.reconcile_sample_size must be positive when set")
    seed = raw.get("reconcile_seed")
    seed = int(seed) if seed is not None else None
    minutes_after_close = int(raw.get("minutes_after_close", 45))
    if minutes_after_close < 0:
        raise ConfigError("schedule.minutes_after_close must be non-negative")

    return ScheduleConfig(
        symbols=symbols,
        history_days=history_days,
        update_cron=_optional_str(raw.get("update_cron")),
        freshness_cron=_optional_str(raw.get("freshness_cron")),
        reconcile_cron=_optional_str(raw.get("reconcile_cron")),
        regime_cron=_optional_str(raw.get("regime_cron")),
        reconcile_sample_size=sample_size,
        reconcile_seed=seed,
        minutes_after_close=minutes_after_close,
        calendar=str(raw.get("calendar", "NYSE")),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_ratio(name: str, value: float) -> None:
    if not 0 < value < 1:
        raise ConfigError(f"{name} must be between 0 and 1")
