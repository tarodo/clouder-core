"""Perplexity sonar adapter via httpx."""

from __future__ import annotations

import json
import time
from typing import Type

import httpx
from pydantic import BaseModel, ValidationError

from .base import VendorResponse
from .pricing import estimate_cost


class PerplexitySonarAdapter:
    name = "perplexity"
    supports_web_search = True

    def __init__(
        self,
        api_key: str,
        default_model: str,
        timeout_s: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.default_model = default_model
        self._api_key = api_key
        self._timeout = timeout_s
        self._client = client or httpx.Client(
            base_url="https://api.perplexity.ai",
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
        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": schema.model_json_schema()},
            },
            "temperature": 0.1,
        }

        started = time.monotonic()
        try:
            response = self._client.post(
                "/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
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
        body = response.json()

        usage = body.get("usage", {}) or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        cost = estimate_cost(chosen_model, input_tokens, output_tokens)
        citations = list(body.get("citations") or [])

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            return VendorResponse(
                parsed=None,
                raw=body,
                citations=citations,
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost,
                },
                latency_ms=latency_ms,
                model=chosen_model,
                error=f"malformed response: {exc}",
            )

        parsed: BaseModel | None = None
        error: str | None = None
        try:
            parsed = schema.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        return VendorResponse(
            parsed=parsed,
            raw=body,
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
