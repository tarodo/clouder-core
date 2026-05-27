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
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3-pro-preview":   (2.00, 12.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),

    # OpenAI GPT
    "gpt-5-mini":  (0.25, 2.00),
    "gpt-5":       (1.25, 10.0),
    "gpt-5-nano":  (0.05, 0.40),
    "gpt-5.4-mini": (0.25, 2.00),
    "gpt-5.4":      (1.25, 10.00),
    "gpt-5.4-nano": (0.05, 0.40),

    # DeepSeek
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro":   (0.435, 0.87),
    "deepseek-chat":     (0.14, 0.28),  # alias

    # Perplexity
    "sonar":     (1.0, 1.0),
    "sonar-pro": (3.0, 15.0),

    # Kimi / Moonshot AI — rates from https://platform.kimi.ai/docs/pricing/chat-k26.md (2026-05-23)
    # Input: $0.95/1M (cache miss) / $0.16/1M (cache hit). Using cache-miss rate as conservative estimate.
    # Output: $4.00/1M tokens.
    # NOTE: The $web_search builtin costs $0.005 per successful search call (finish_reason="tool_calls")
    # on top of token charges; this per-call cost is NOT captured by estimate_cost().
    "kimi-k2.6": (0.95, 4.00),
    "kimi-k2.5": (0.95, 4.00),   # estimated — same tier as k2.6; no separate pricing page consulted
    "kimi-k2-thinking": (0.95, 4.00),  # estimated — no dedicated pricing found
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    in_rate, out_rate = PRICING[model]
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
