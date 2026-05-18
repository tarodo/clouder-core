"""Google Gemini 2.5 Flash adapter via the google-genai SDK."""

from __future__ import annotations

import json
import re
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
        "\n\nIMPORTANT — OUTPUT FORMAT:\n"
        "Return ONLY a single JSON object that conforms to this schema. "
        "No prose, no markdown fences, no explanation. Just the JSON.\n"
        "Schema:\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}"
    )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Strip markdown fences and return the first balanced JSON object substring."""
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


_RETRY_DELAY_RE = re.compile(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'")


def _parse_retry_delay(message: str) -> float:
    m = _RETRY_DELAY_RE.search(message)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 10.0
    return 10.0


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

            # Bug fix: response_mime_type + response_schema are incompatible with
            # tools=[google_search] (HTTP 400 INVALID_ARGUMENT). Drop both; rely on
            # the schema hint in system_instruction and parse the raw text ourselves.
            config = types.GenerateContentConfig(
                system_instruction=system + _schema_hint(schema),
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )

            attempts = 0
            deadline = time.monotonic() + self._timeout * 6
            backoff_floor = 10.0
            while True:
                try:
                    response = self._client.models.generate_content(
                        model=chosen_model,
                        contents=user,
                        config=config,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    exc_msg = str(exc)
                    is_quota = (
                        "RESOURCE_EXHAUSTED" in exc_msg
                        or "429" in exc_msg
                        or type(exc).__name__ == "ResourceExhausted"
                    )
                    is_unavailable = (
                        "UNAVAILABLE" in exc_msg
                        or "503" in exc_msg
                        or type(exc).__name__ == "ServerError"
                    )
                    if not (is_quota or is_unavailable):
                        raise
                    attempts += 1
                    if attempts > 5 or time.monotonic() >= deadline:
                        raise
                    if is_quota:
                        wait = max(_parse_retry_delay(exc_msg), backoff_floor)
                    else:
                        wait = backoff_floor
                    time.sleep(wait)
                    backoff_floor = min(backoff_floor * 1.5, 60.0)

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
            parsed = schema.model_validate_json(_extract_json(text))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        if not citations and parsed is not None:
            src = getattr(parsed, "sources", None)
            if isinstance(src, list):
                citations = [s for s in src if isinstance(s, str) and s.strip()]

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
