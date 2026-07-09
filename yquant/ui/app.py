"""Streamlit six-page shell (03 §5.6).

This module is a thin renderer over :mod:`yquant.ui.viewmodels`: it turns the
already-assembled, JSON-safe view models into Streamlit widgets. All business
logic (the checklist gate, the report contract, the Thesis sentinel) lives in
the view models so it is unit-tested without a browser; this file is intentionally
kept side-effect-thin and is excluded from coverage (see pyproject ``omit``).

Run with::

    streamlit run yquant/ui/app.py

In practice the page is driven by :func:`yquant.ui.demo.build_demo_payload`,
which wires the real deterministic engines (regime machine, committee, backtest,
discipline) into the six view models.
"""

from __future__ import annotations

from typing import Any

from yquant.ui.viewmodels import PAGE_TITLES


def _st() -> Any:
    import streamlit as st

    return st


def render(payload: dict[str, Any]) -> None:
    """Render the six pages from a demo payload (see :mod:`yquant.ui.demo`)."""

    st = _st()
    st.set_page_config(page_title="yquant", layout="wide")
    page = st.sidebar.radio("导航", PAGE_TITLES)

    if page == PAGE_TITLES[0]:
        _render_today_brief(st, payload["today_brief"])
    elif page == PAGE_TITLES[1]:
        _render_opportunity_risk(st, payload["opportunity_risk"])
    elif page == PAGE_TITLES[2]:
        _render_portfolio_risk(st, payload["portfolio_risk"])
    elif page == PAGE_TITLES[3]:
        _render_backtest_lab(st, payload["backtest_lab"])
    elif page == PAGE_TITLES[4]:
        _render_trade_journal(st, payload["trade_journal"])
    else:
        _render_system_health(st, payload["system_health"])


def _render_today_brief(st: Any, view: dict[str, Any]) -> None:
    st.header("今日简报")
    weather = view["weather"]
    st.subheader(f"全球天气：{weather['state']}（composite {weather['composite']}）")
    st.json(weather["pillar_scores"])
    st.subheader("今日必看 Top3")
    for card in view["top3"]:
        st.markdown(f"**{card['symbol']}** · {card['event_type']} · S{card['severity']}"
                    f" · {card['direction']} — {card['one_line']}")
    st.subheader("事件卡流")
    st.table(view["event_cards"])


def _render_opportunity_risk(st: Any, view: dict[str, Any]) -> None:
    st.header("机会与风险")
    st.subheader("Top5 风险仪表盘")
    st.table(view["dashboard"])
    st.subheader(f"机会簿（Overlay 合计 {view['total_overlay_weight']:.2%}）")
    st.table(view["opportunity_book"])
    st.subheader("Thesis 哨兵")
    st.table([row for row in view["thesis_sentinel"]])


def _render_portfolio_risk(st: Any, view: dict[str, Any]) -> None:
    st.header("组合与风控")
    st.subheader("三层预算水位")
    st.json(view["layer_weights"])
    if view["overlay_breach"]:
        st.error("P11: Overlay 敞口超过 10% — S1 告警")
    st.metric("NAV", view["nav"], delta=view["nav"] - view["benchmark_nav"])
    st.metric("回撤", view["drawdown"])
    st.subheader("风险事件")
    st.table(view["risk_events"])


def _render_backtest_lab(st: Any, view: dict[str, Any]) -> None:
    st.header("回测实验室")
    st.subheader("成本三档 vs SPY 买入持有")
    st.table(view["cost_sensitivity"])
    st.json(view["benchmark"])
    st.subheader("样本外 walk-forward")
    st.table(view["walk_forward"])
    if view["warnings"]:
        st.warning("\n".join(view["warnings"]))


def _render_trade_journal(st: Any, view: dict[str, Any]) -> None:
    st.header("交易台账")
    for row in view["rows"]:
        st.markdown(f"### {row['symbol']} · {row['side']} · {row['layer']}")
        if row["can_execute"]:
            st.success("六项 checklist 已通过，可标记已执行")
        else:
            st.error(f"未满足项：{row['unmet_checklist_items']}")
        if row["slippage_bps"] is not None:
            st.metric("滑点 (bps)", row["slippage_bps"])
    if view["mean_slippage_bps"] is not None:
        st.metric("平均滑点 (bps)", view["mean_slippage_bps"])


def _render_system_health(st: Any, view: dict[str, Any]) -> None:
    st.header("设置与系统健康")
    st.subheader("P 指标")
    st.json(view["p_metrics"])
    st.subheader("数据新鲜度")
    st.json(view["data_freshness"])
    st.subheader("任务日志")
    st.table(view["job_runs"])
    st.subheader("LLM 用量")
    st.json(view["llm_usage"])


def main() -> None:  # pragma: no cover - entrypoint
    from yquant.ui.demo import build_demo_payload

    render(build_demo_payload().to_dict())


if __name__ == "__main__":  # pragma: no cover
    main()
