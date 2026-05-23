from collector.label_enrichment.vendors.pricing import estimate_cost


def test_known_model():
    # gemini-3-flash-preview: 0.50 in, 3.00 out per 1M tokens
    assert estimate_cost("gemini-3-flash-preview", 1_000_000, 1_000_000) == 3.50


def test_gemini_3_5_flash_pricing():
    # gemini-3.5-flash: 1.50 in, 9.00 out per 1M tokens
    assert estimate_cost("gemini-3.5-flash", 1_000_000, 1_000_000) == 10.50


def test_unknown_model_zero():
    assert estimate_cost("unknown-xyz", 1_000_000, 1_000_000) == 0.0


def test_fractional_tokens():
    # gpt-5.4-mini: 0.25 in, 2.00 out per 1M
    cost = estimate_cost("gpt-5.4-mini", 100_000, 50_000)
    assert abs(cost - (0.025 + 0.1)) < 1e-9
