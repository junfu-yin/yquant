from __future__ import annotations

import pytest

from yquant.risk.regime import compute_risk_on


def test_risk_on_when_trend_up_and_vix_low() -> None:
    regime = compute_risk_on(market_trend_ok=True, vix_level=15.0, vix_threshold=25.0)
    assert regime.risk_on is True


def test_risk_off_when_trend_down() -> None:
    regime = compute_risk_on(market_trend_ok=False, vix_level=12.0)
    assert regime.risk_on is False
    assert regime.reason == "market_trend_down"


def test_risk_off_when_vix_elevated() -> None:
    regime = compute_risk_on(market_trend_ok=True, vix_level=30.0, vix_threshold=25.0)
    assert regime.risk_on is False
    assert "vix" in regime.reason


def test_missing_vix_degrades_to_trend_only() -> None:
    regime = compute_risk_on(market_trend_ok=True, vix_level=None)
    assert regime.risk_on is True


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ValueError, match="vix_threshold"):
        compute_risk_on(market_trend_ok=True, vix_level=10.0, vix_threshold=0.0)
