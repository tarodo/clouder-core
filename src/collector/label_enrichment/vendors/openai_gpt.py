"""OpenAI GPT adapter via the Responses API."""

from __future__ import annotations

import time
from typing import Any, Type

from pydantic import BaseModel

from .base import VendorResponse
from .pricing import estimate_cost


def _zero_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def _lat(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class OpenAIAdapter:
    name = "openai"
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

            # web_search runs are long; the SDK's default retries (2) compound
            # the timeout to ~3x and re-run the web search each time. Disable
            # them — the SQS/worker layer owns retry.
            self._client = OpenAI(
                api_key=api_key, timeout=timeout_s, max_retries=0
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
        try:
            response = self._client.responses.parse(
                model=chosen_model,
                input=[{"role": "user", "content": user}],
                instructions=system,
                tools=[{"type": "web_search"}],
                text_format=schema,
            )
        except Exception as exc:  # noqa: BLE001 — never raise
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

        input_tokens = 0
        output_tokens = 0
        citations: list[str] = []
        raw_dump: dict = {}
        parse_error: str | None = None
        parsed: BaseModel | None = None

        try:
            usage = getattr(response, "usage", None)
            if usage is not None:
                input_tokens = (
                    getattr(usage, "input_tokens", None)
                    or getattr(usage, "prompt_tokens", None)
                    or 0
                )
                output_tokens = (
                    getattr(usage, "output_tokens", None)
                    or getattr(usage, "completion_tokens", None)
                    or 0
                )

            citations = list(getattr(response, "citations", None) or [])
            # Some SDK versions surface citations inside output items.
            if not citations:
                for item in getattr(response, "output", None) or []:
                    item_type = getattr(item, "type", None)
                    if item_type and "search" in item_type.lower():
                        for c in getattr(item, "citations", None) or []:
                            url = getattr(c, "url", None) or (c.get("url") if isinstance(c, dict) else None)
                            if url:
                                citations.append(url)

            parsed = getattr(response, "output_parsed", None)
            raw_dump = _to_dict(response)
        except Exception as exc:  # noqa: BLE001
            parse_error = f"parse error: {type(exc).__name__}: {exc}"

        cost = estimate_cost(chosen_model, input_tokens, output_tokens)

        error: str | None = parse_error
        if error is None and parsed is None:
            error = "no output_parsed in Responses API response"

        return VendorResponse(
            parsed=parsed,
            raw=raw_dump,
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
    """Best-effort serialization for the `raw` field.

    SDK Response objects use TypeVar-discriminated unions that pydantic
    warns about during model_dump. Pass `warnings="none"` to silence them.
    """
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(warnings="none")
        except TypeError:
            return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: getattr(obj, k) for k in vars(obj) if not k.startswith("_")}
    return {"repr": repr(obj)}
