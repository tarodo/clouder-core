"""xAI Grok adapter via the OpenAI-compatible API."""

from __future__ import annotations

import json
import time
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from .base import VendorResponse
from .pricing import estimate_cost


class XAIGrokAdapter:
    name = "xai"
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
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1",
                timeout=timeout_s,
            )

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen_model = model or self.default_model
        json_schema = {
            "name": "label_info",
            "schema": schema.model_json_schema(),
        }

        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_schema", "json_schema": json_schema},
                tools=[{"type": "live_search"}],
            )
        except Exception as exc:  # noqa: BLE001
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

        # Defensive extraction — never raise from here on.
        input_tokens = 0
        output_tokens = 0
        content = ""
        citations: list[str] = []
        try:
            usage = response.usage
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            content = response.choices[0].message.content or ""
            citations = list(getattr(response, "citations", []) or [])
        except Exception as exc:  # noqa: BLE001
            cost = estimate_cost(chosen_model, input_tokens, output_tokens)
            return VendorResponse(
                parsed=None,
                raw={"content": content, "citations": citations},
                citations=citations,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost},
                latency_ms=latency_ms,
                model=chosen_model,
                error=f"malformed response: {type(exc).__name__}: {exc}",
            )

        cost = estimate_cost(chosen_model, input_tokens, output_tokens)

        parsed: BaseModel | None = None
        error: str | None = None
        try:
            parsed = schema.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        return VendorResponse(
            parsed=parsed,
            raw={"content": content, "citations": citations},
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
