"""Pre-registered layered interval-book (08 §4, ADR-23/24).

Before real money is deployed the plan requires a signed *interval book*: the
range of outcomes we commit to **in advance**, so that a live result outside the
band (in either direction, "含好得反常") triggers an investigation rather than a
post-hoc story. v3 makes it *layered* because the layers have fundamentally
different predictability:

* **core (C1–C3 rule strategies)** — a numeric band is honest: it is the
  10/50/90 percentile of the *out-of-sample* walk-forward distribution.
* **satellite S-A (rule)** — same treatment as core.
* **satellite S-B/S-C (LLM)** — forward-unknown; a numeric band would be a lie.
  We register *process* metrics only and stamp the return band ``observing``.
* **overlay** — tactical; we register the process metrics from the paper
  opportunity book (hit-rate baseline, stop-loss execution = 100%), never a
  return band.

The band is derived from :func:`~yquant.backtest.walkforward.stitch_oos_metrics`
so it is reproducible and cannot be hand-tuned. This module is the *template +
first instance* deliverable; a signed copy is written to the ledger at L3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd

from yquant.backtest.walkforward import run_walk_forward, stitch_oos_metrics
from yquant.strategies.adapters import (
    make_dual_momentum_provider,
    make_sector_momentum_provider,
)
from yquant.strategies.satellite import GICS_SECTOR_ETFS

LayerKind = Literal["numeric", "observing"]


@dataclass(frozen=True)
class IntervalBand:
    """A pre-registered 10/50/90 band for one metric (numeric layers only)."""

    metric: str
    p10: float
    p50: float
    p90: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "p10": round(self.p10, 6),
            "p50": round(self.p50, 6),
            "p90": round(self.p90, 6),
        }


@dataclass(frozen=True)
class LayerIntervalBook:
    """One layer's section of the interval book."""

    layer: str
    strategies: tuple[str, ...]
    kind: LayerKind
    bands: tuple[IntervalBand, ...]
    process_metrics: dict[str, str]
    hard_caps: dict[str, float]
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "strategies": list(self.strategies),
            "kind": self.kind,
            "bands": [band.as_dict() for band in self.bands],
            "process_metrics": dict(sorted(self.process_metrics.items())),
            "hard_caps": {k: round(v, 6) for k, v in sorted(self.hard_caps.items())},
            "note": self.note,
        }


@dataclass(frozen=True)
class IntervalBook:
    """The signed, layered interval book (08 §4)."""

    as_of: date
    version: str
    num_oos_windows: int
    layers: tuple[LayerIntervalBook, ...] = field(default_factory=tuple)

    def layer(self, name: str) -> LayerIntervalBook | None:
        for section in self.layers:
            if section.layer == name:
                return section
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "version": self.version,
            "num_oos_windows": self.num_oos_windows,
            "layers": [section.as_dict() for section in self.layers],
        }


def bands_from_oos(summary: dict[str, Any]) -> tuple[IntervalBand, ...]:
    """Turn a ``stitch_oos_metrics`` summary into pre-registered bands.

    Empty (too little history for any OOS window) yields no bands rather than a
    fabricated zero band — an honest "insufficient sample" is preferable to a
    misleading point estimate.
    """

    if not summary.get("num_windows"):
        return ()
    ann = summary["annualized_return_pctile"]
    mdd = summary["max_drawdown_pctile"]
    return (
        IntervalBand("annualized_return", ann["p10"], ann["p50"], ann["p90"]),
        IntervalBand("max_drawdown", mdd["p10"], mdd["p50"], mdd["p90"]),
    )


def _core_oos_summary(bars: pd.DataFrame, *, initial_cash: float) -> dict[str, Any]:
    """Run the C1 dual-momentum walk-forward and stitch its OOS distribution."""

    def factory(window_bars: pd.DataFrame) -> Any:
        return make_dual_momentum_provider(window_bars)

    windows = run_walk_forward(
        bars=bars,
        provider_factory=factory,
        initial_cash=initial_cash,
        is_months=24,
        oos_months=12,
    )
    return stitch_oos_metrics(windows)


def _satellite_rule_oos_summary(
    bars: pd.DataFrame,
    *,
    initial_cash: float,
) -> dict[str, Any]:
    """Run an independent S-A sector-momentum walk-forward."""

    sector_bars = bars.loc[bars["symbol"].astype(str).isin(GICS_SECTOR_ETFS)].copy()
    if sector_bars.empty:
        return {"num_windows": 0, "windows": []}

    def factory(window_bars: pd.DataFrame) -> Any:
        return make_sector_momentum_provider(window_bars)

    windows = run_walk_forward(
        bars=sector_bars,
        provider_factory=factory,
        initial_cash=initial_cash,
        is_months=24,
        oos_months=12,
    )
    return stitch_oos_metrics(windows)


def build_interval_book(
    bars: pd.DataFrame,
    *,
    as_of: date,
    initial_cash: float = 50_000.0,
    version: str = "v1",
) -> IntervalBook:
    """Assemble the layered interval book from a real OOS walk-forward run.

    ``bars`` is a canonical daily-bar frame (typically several years of the C1
    asset pool). The core band is derived, never typed in; satellite-LLM and
    overlay carry process metrics and ``observing`` bands per ADR-23/24.
    """

    core_summary = _core_oos_summary(bars, initial_cash=initial_cash)
    satellite_summary = _satellite_rule_oos_summary(bars, initial_cash=initial_cash)
    core_bands = bands_from_oos(core_summary)
    satellite_bands = bands_from_oos(satellite_summary)

    core = LayerIntervalBook(
        layer="core",
        strategies=("C1", "C2", "C3"),
        kind="numeric",
        bands=core_bands,
        process_metrics={
            "rebalance": "monthly (C1/C2), weekly (C3 vol target)",
            "sample": "out-of-sample walk-forward, 24m IS / 12m OOS",
        },
        hard_caps={},
        note=(
            "核心层承载降险目标：区间取 walk-forward 样本外 10/50/90 分位，"
            "含趋势/波动目标的踏空成本（保险费）。"
        ),
    )
    satellite_rule = LayerIntervalBook(
        layer="satellite_rule",
        strategies=("S-A",),
        kind="numeric",
        bands=satellite_bands,
        process_metrics={
            "rebalance": "monthly sector-momentum",
            "sample": (
                f"independent out-of-sample walk-forward, "
                f"{int(satellite_summary.get('num_windows', 0))} windows"
            ),
        },
        hard_caps={"single_name": 0.05},
        note="S-A 为规则型，使用其自身行业动量样本外窗口计算区间。",
    )
    satellite_llm = LayerIntervalBook(
        layer="satellite_llm",
        strategies=("S-B", "S-C"),
        kind="observing",
        bands=(),
        process_metrics={
            "return_band": "observing (前向未知，论文夏普不构成预期)",
            "coverage": "register forward",
            "abstention_rate": "register forward",
        },
        hard_caps={"s_b_cap": 0.10, "s_c_cap": 0.05},
        note="S-B/S-C 前向未知：只预注册过程指标，仓位帽为唯一硬约束（ADR-24）。",
    )
    overlay = LayerIntervalBook(
        layer="overlay",
        strategies=("tactical",),
        kind="observing",
        bands=(),
        process_metrics={
            "hit_rate_baseline": "observing (纸上机会簿期实测)",
            "invalidation_stop_execution": "100%",
            "regime_veto_compliance": "100%",
            "red_team_reject_rate": "register forward",
        },
        hard_caps={"overlay_total": 0.10, "leveraged_2x_total": 0.05},
        note="Overlay 为战术层：只预注册过程指标；10% 为合同级硬上限。",
    )

    return IntervalBook(
        as_of=as_of,
        version=version,
        num_oos_windows=int(core_summary.get("num_windows", 0)),
        layers=(core, satellite_rule, satellite_llm, overlay),
    )
