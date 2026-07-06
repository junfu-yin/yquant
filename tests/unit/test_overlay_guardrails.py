from yquant.discipline.overlay_guardrails import (
    OverlayExposure,
    required_layer_for_request,
    validate_overlay_request,
)


def test_discretionary_and_meme_requests_are_overlay() -> None:
    assert (
        required_layer_for_request(
            "core", instrument_kind="discretionary", is_system_signal=False
        )
        == "overlay"
    )
    assert (
        required_layer_for_request(
            "satellite", instrument_kind="meme_stock", is_system_signal=True
        )
        == "overlay"
    )


def test_system_core_signal_keeps_layer() -> None:
    assert (
        required_layer_for_request("core", instrument_kind="ordinary", is_system_signal=True)
        == "core"
    )


def test_overlay_total_and_single_caps_block_even_with_high_confidence() -> None:
    violations = validate_overlay_request(
        symbol="NVDA",
        instrument_kind="discretionary",
        exposure=OverlayExposure(
            overlay_weight_after=0.11,
            symbol_weight_after=0.06,
            confidence=0.99,
        ),
    )

    rules = {violation.rule for violation in violations}
    assert "overlay_cap" in rules
    assert "overlay_single_cap" in rules


def test_2x_long_etf_caps() -> None:
    violations = validate_overlay_request(
        symbol="SSO",
        instrument_kind="leveraged_2x_long",
        exposure=OverlayExposure(
            overlay_weight_after=0.05,
            symbol_weight_after=0.04,
            leveraged_2x_weight_after=0.06,
        ),
    )

    rules = {violation.rule for violation in violations}
    assert "leveraged_2x_total_cap" in rules
    assert "leveraged_2x_single_cap" in rules


def test_3x_and_inverse_are_rejected() -> None:
    three_x = validate_overlay_request(
        symbol="TQQQ",
        instrument_kind="leveraged_3x",
        exposure=OverlayExposure(overlay_weight_after=0.01, symbol_weight_after=0.01),
    )
    inverse = validate_overlay_request(
        symbol="SQQQ",
        instrument_kind="inverse",
        exposure=OverlayExposure(overlay_weight_after=0.01, symbol_weight_after=0.01),
    )

    assert {violation.rule for violation in three_x} == {
        "icebox_ticker",
        "leveraged_3x_not_allowed",
    }
    assert {violation.rule for violation in inverse} == {
        "icebox_ticker",
        "inverse_not_allowed",
    }

