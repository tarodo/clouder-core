"""Google Gemini 2.5 Flash adapter via the google-genai SDK."""

from __future__ import annotations

import json
import time
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from .base import VendorResponse
from .pricing import estimate_cost


def _zero_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def _lat(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _schema_hint(schema: Type[BaseModel]) -> str:
    return (
        "\n\nIf you cannot use structured output, return ONLY a JSON object matching "
        "this schema:\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}"
    )


class GeminiFlashAdapter:
    name = "gemini"
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
            from google import genai

            self._client = genai.Client(api_key=api_key)

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen_model = model or self.default_model
        started = time.monotonic()
        try:
            from google.genai import types  # lazy

            config = types.GenerateContentConfig(
                system_instruction=system + _schema_hint(schema),
                tools=[types.Tool(google_search=types.GoogleSearch())],
                response_mime_type="application/json",
                response_schema=schema,
            )
            response = self._client.models.generate_content(
                model=chosen_model,
                contents=user,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001
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
        # defensive extraction (never raise from here)
        try:
            text = response.text or ""
            usage_meta = getattr(response, "usage_metadata", None)
            input_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
            citations: list[str] = []
            for cand in getattr(response, "candidates", None) or []:
                meta = getattr(cand, "grounding_metadata", None)
                for chunk in getattr(meta, "grounding_chunks", None) or []:
                    web = getattr(chunk, "web", None)
                    uri = getattr(web, "uri", None) if web else None
                    if uri:
                        citations.append(uri)
        except Exception as exc:  # noqa: BLE001
            return VendorResponse(
                parsed=None,
                raw={"error": "extract failure"},
                citations=[],
                usage=_zero_usage(),
                latency_ms=latency_ms,
                model=chosen_model,
                error=f"extract error: {exc}",
            )

        cost = estimate_cost(chosen_model, input_tokens, output_tokens)
        parsed: BaseModel | None = None
        error: str | None = None
        try:
            parsed = schema.model_validate_json(text)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        return VendorResponse(
            parsed=parsed,
            raw={"text": text, "citations": citations},
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
