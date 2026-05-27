import pytest

from artlab.vendors.pricing import estimate_cost


def test_estimate_anthropic_sonnet():
    # Pricing assumption: Sonnet 4.6 ≈ $3 / Mtok input, $15 / Mtok output
    cost = estimate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    assert cost == pytest.approx(0.003 + 0.0075, rel=1e-3)


def test_estimate_unknown_model_returns_zero():
    cost = estimate_cost("does-not-exist", input_tokens=1000, output_tokens=500)
    assert cost == 0.0


def test_estimate_zero_tokens():
    assert estimate_cost("claude-sonnet-4-6", 0, 0) == 0.0
