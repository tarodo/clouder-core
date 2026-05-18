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

    # Google Gemini
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro":   (1.25, 10.0),

    # OpenAI GPT
    "gpt-5-mini":  (0.25, 2.00),
    "gpt-5":       (1.25, 10.0),
    "gpt-5-nano":  (0.05, 0.40),

    # DeepSeek
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro":   (0.435, 0.87),
    "deepseek-chat":     (0.14, 0.28),  # alias

    # Perplexity
    "sonar":     (1.0, 1.0),
    "sonar-pro": (3.0, 15.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    in_rate, out_rate = PRICING[model]
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
