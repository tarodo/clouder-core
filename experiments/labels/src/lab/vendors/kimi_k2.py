"""Kimi (Moonshot AI) adapter via the OpenAI-compatible SDK with $web_search builtin."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from .base import VendorResponse
from .pricing import estimate_cost

# Max iterations for the $web_search tool-call loop (guards against infinite loops).
_MAX_LOOP_ITER = 5

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _zero_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def _lat(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _extract_json(text: str) -> str:
    """Strip markdown fences and return the first balanced JSON object substring."""
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _schema_hint(schema: Type[BaseModel]) -> str:
    return (
        "\n\nIMPORTANT — OUTPUT FORMAT:\n"
        "Return ONLY a single JSON object that conforms to this schema. "
        "No prose, no markdown fences, no explanation. Just the JSON.\n"
        "Schema:\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}"
    )


# The $web_search builtin tool definition for Moonshot AI.
_WEB_SEARCH_TOOL = {
    "type": "builtin_function",
    "function": {
        "name": "$web_search",
    },
}


class KimiAdapter:
    name = "kimi"
    supports_web_search = True

    def __init__(
        self,
        api_key: str,
        default_model: str,
        timeout_s: float = 180.0,
        client: Any | None = None,
    ) -> None:
        self.default_model = default_model
        self._timeout = timeout_s
        if client is not None:
            self._client = client
        else:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key,
                base_url="https://api.moonshot.ai/v1",
                timeout=timeout_s,
                max_retries=0,
            )

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen_model = model or self.default_model
        started = time.monotonic()

        messages: list[dict] = [
            {"role": "system", "content": system + _schema_hint(schema)},
            {"role": "user", "content": user},
        ]

        input_tokens = 0
        output_tokens = 0
        final_content: str | None = None

        try:
            for _iteration in range(_MAX_LOOP_ITER):
                response = self._client.chat.completions.create(
                    model=chosen_model,
                    messages=messages,
                    tools=[_WEB_SEARCH_TOOL],
                )
                choice = response.choices[0]
                finish_reason = choice.finish_reason

                # Accumulate token usage across all loop iterations.
                if response.usage is not None:
                    input_tokens += getattr(response.usage, "prompt_tokens", 0) or 0
                    output_tokens += getattr(response.usage, "completion_tokens", 0) or 0

                if finish_reason == "stop":
                    final_content = choice.message.content
                    break

                if finish_reason == "tool_calls" and choice.message.tool_calls:
                    # Append the assistant message with the tool_calls.
                    messages.append(choice.message)
                    # Echo each tool call result back (Moonshot executes server-side).
                    for tool_call in choice.message.tool_calls:
                        tool_call_name = tool_call.function.name
                        # Parse arguments, then echo them back serialised as a string.
                        try:
                            tool_call_arguments = json.loads(tool_call.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            tool_call_arguments = {}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call_name,
                            "content": json.dumps(tool_call_arguments),
                        })
                    # Continue the loop for the next model call.
                    continue

                # Unexpected finish_reason — treat as done with whatever content we have.
                final_content = choice.message.content
                break
            else:
                # Exhausted max iterations without reaching stop.
                final_content = None

        except Exception as exc:  # noqa: BLE001 — never raise from adapter
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage=_zero_usage(),
                latency_ms=_lat(started),
                model=chosen_model,
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = _lat(started)

        if not final_content:
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": estimate_cost(chosen_model, input_tokens, output_tokens),
                },
                latency_ms=latency_ms,
                model=chosen_model,
                error="no content in response after tool-call loop",
            )

        cost = estimate_cost(chosen_model, input_tokens, output_tokens)
        parsed: BaseModel | None = None
        error: str | None = None
        try:
            parsed = schema.model_validate_json(_extract_json(final_content))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        return VendorResponse(
            parsed=parsed,
            raw={"content": final_content},
            citations=[],
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            },
            latency_ms=latency_ms,
            model=chosen_model,
            error=error,
        )
