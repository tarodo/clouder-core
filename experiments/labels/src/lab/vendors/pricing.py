"""Approximate per-model pricing in USD per million tokens.

Values are informational only. Outdated entries are tolerable.
Update by editing the PRICING table.
"""

from __future__ import annotations

# (model_id -> (input_usd_per_mtok, output_usd_per_mtok))
PRICING: dict[str, tuple[float, float]] = {
    # Anthropic Claude
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),

    # xAI Grok
    "grok-4": (5.0, 15.0),
    "grok-2": (2.0, 10.0),

    # Perplexity
    "sonar":     (1.0, 1.0),
    "sonar-pro": (3.0, 15.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    in_rate, out_rate = PRICING[model]
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
