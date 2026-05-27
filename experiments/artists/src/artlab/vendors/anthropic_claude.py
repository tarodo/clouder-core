"""Anthropic Claude adapter."""

from __future__ import annotations

import time
from typing import Any, Type

from pydantic import BaseModel

from .base import VendorResponse
from .pricing import estimate_cost


class AnthropicClaudeAdapter:
    name = "anthropic"
    supports_web_search = True

    def __init__(
        self,
        api_key: str,
        default_model: str,
        timeout_s: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self.default_model = default_model
        self._timeout = timeout_s
        if client is not None:
            self._client = client
        else:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=api_key, timeout=timeout_s)

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen_model = model or self.default_model
        emit_tool = {
            "name": "emit_artist_info",
            "description": (
                "Return the requested artist info by invoking this tool exactly "
                "once with the full structured payload."
            ),
            "input_schema": schema.model_json_schema(),
        }
        web_search_tool = {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }

        RETRYABLE = {"RateLimitError", "APIConnectionError"}

        started = time.monotonic()
        try:
            attempts = 0
            deadline = time.monotonic() + self._timeout * 6
            backoff = 10.0
            while True:
                try:
                    response = self._client.messages.create(
                        model=chosen_model,
                        max_tokens=4096,
                        system=system,
                        messages=[{"role": "user", "content": user}],
                        tools=[web_search_tool, emit_tool],
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    exc_name = type(exc).__name__
                    if exc_name not in RETRYABLE:
                        raise
                    attempts += 1
                    if attempts > 5 or time.monotonic() >= deadline:
                        raise
                    retry_after = None
                    if exc_name == "RateLimitError":
                        try:
                            retry_after = float(exc.response.headers.get("retry-after"))
                        except (TypeError, ValueError, AttributeError):
                            pass
                    wait = retry_after if retry_after is not None else min(backoff, 60.0)
                    time.sleep(wait)
                    backoff = min(backoff * 2, 60.0)
        except Exception as exc:  # noqa: BLE001 — adapter contract: never raise
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                latency_ms=int((time.monotonic() - started) * 1000),
                model=chosen_model,
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        input_tokens = getattr(response.usage, "input_tokens", 0)
        output_tokens = getattr(response.usage, "output_tokens", 0)
        cost = estimate_cost(chosen_model, input_tokens, output_tokens)

        parsed: BaseModel | None = None
        citations: list[str] = []
        parse_error: str | None = None
        try:
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "emit_artist_info":
                    parsed = schema.model_validate(block.input)
                elif getattr(block, "type", None) == "web_search_tool_result":
                    for item in getattr(block, "content", []) or []:
                        url = getattr(item, "url", None) or (item.get("url") if isinstance(item, dict) else None)
                        if url:
                            citations.append(url)
        except Exception as exc:  # noqa: BLE001 — adapter contract: never raise
            parse_error = f"parse error: {type(exc).__name__}: {exc}"

        error: str | None = parse_error
        if error is None and parsed is None:
            error = "no tool_use(emit_artist_info) block in response"

        return VendorResponse(
            parsed=parsed,
            raw=_to_dict(response),
            citations=citations,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            },
            latency_ms=latency_ms,
            model=chosen_model,
            error=error,
        )


def _to_dict(obj: Any) -> dict:
    """Best-effort serialization for the `raw` field. SDK objects vary in shape."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: getattr(obj, k) for k in vars(obj) if not k.startswith("_")}
    return {"repr": repr(obj)}
