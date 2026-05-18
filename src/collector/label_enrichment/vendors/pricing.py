"""Approximate per-model pricing in USD per million tokens.

Values are informational only — used to compute cost estimates that
accumulate into the run row's cost_usd column.
"""

from __future__ import annotations

PRICING: dict[str, tuple[float, float]] = {
    # Google Gemini
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro":   (1.25, 10.0),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3-pro-preview":   (2.00, 12.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),

    # OpenAI GPT
    "gpt-5-mini":   (0.25, 2.00),
    "gpt-5":        (1.25, 10.0),
    "gpt-5-nano":   (0.05, 0.40),
    "gpt-5.4-mini": (0.25, 2.00),
    "gpt-5.4":      (1.25, 10.00),
    "gpt-5.4-nano": (0.05, 0.40),

    # DeepSeek (used for Tavily synthesis stage AND the narrative merge)
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro":   (0.435, 0.87),
    "deepseek-chat":     (0.14, 0.28),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    in_rate, out_rate = PRICING[model]
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
