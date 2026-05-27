"""Tavily + DeepSeek two-stage adapter.

Stage 1: Tavily search retrieves relevant web snippets.
Stage 2: DeepSeek synthesises the snippets into a structured JSON response.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Type

import httpx
from pydantic import BaseModel, ValidationError

from .base import VendorResponse
from .pricing import estimate_cost

_QUOTED_RE = re.compile(r'"([^"]+)"')


def _build_search_query(user: str) -> str:
    """Build a focused Tavily query from the rendered user prompt.

    The artist prompt quotes the artist name; the disambiguation context
    (tracks, labels, genre) is unquoted. Extract the first quoted string as
    the artist name and build a focused query. Fall back to the full prompt
    if no quoted name is found.
    """
    matches = _QUOTED_RE.findall(user)
    if matches:
        artist_name = matches[0].strip()
        if artist_name:
            return f'"{artist_name}" music artist'
    return user


SOCIAL_DOMAINS = [
    "youtube.com",
    "soundcloud.com",
    "bandcamp.com",
    "beatport.com",
    "discogs.com",
    "ra.co",
    "spotify.com",
    "instagram.com",
]


def _zero_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def _lat(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class TavilyDeepSeekAdapter:
    name = "tavily_deepseek"
    supports_web_search = True

    def __init__(
        self,
        tavily_api_key: str,
        deepseek_api_key: str,
        default_model: str,
        timeout_s: float = 180.0,
        http_client: httpx.Client | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self.default_model = default_model
        self._tavily_key = tavily_api_key
        self._deepseek_key = deepseek_api_key
        self._timeout = timeout_s
        self._http = http_client or httpx.Client(timeout=timeout_s)
        if llm_client is not None:
            self._llm = llm_client
        else:
            from openai import OpenAI

            self._llm = OpenAI(
                api_key=deepseek_api_key,
                base_url="https://api.deepseek.com",
                timeout=timeout_s,
            )

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen = model or self.default_model
        search_query = _build_search_query(user)
        started = time.monotonic()

        # Stage 1 — Tavily search
        try:
            tavily_resp = self._http.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._tavily_key,
                    "query": search_query,
                    "search_depth": "advanced",
                    "max_results": 8,
                    "include_answer": False,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            tavily_resp.raise_for_status()
            tavily_body = tavily_resp.json()
        except Exception as exc:  # noqa: BLE001
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage=_zero_usage(),
                latency_ms=_lat(started),
                model=chosen,
                error=f"tavily error: {type(exc).__name__}: {exc}",
            )

        results = tavily_body.get("results") or []

        # Stage 1b — Tavily second pass restricted to social/music domains
        social_results: list[dict] = []
        try:
            social_resp = self._http.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._tavily_key,
                    "query": search_query,
                    "search_depth": "advanced",
                    "max_results": 5,
                    "include_answer": False,
                    "include_domains": SOCIAL_DOMAINS,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            social_resp.raise_for_status()
            social_results = (social_resp.json().get("results") or [])
        except Exception:  # noqa: BLE001 — second call is best-effort; failure leaves general results intact
            social_results = []

        # Merge + dedup by URL
        seen_urls: set[str] = set()
        merged: list[dict] = []
        for r in (results or []) + social_results:
            url = r.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(r)
        results = merged

        citations = [r.get("url") for r in results if r.get("url")]
        snippets_block = "\n\n".join(
            f"[{i + 1}] {r.get('title', '')}\nURL: {r.get('url', '')}\n{r.get('content', '')[:500]}"
            for i, r in enumerate(results)
        )

        # Stage 2 — DeepSeek synthesis
        synth_user = (
            f"{user}\n\n"
            f"Search results (use these as your sources; cite their URLs in the `sources` field):\n"
            f"{snippets_block}\n\n"
            f"Output ONLY a single JSON object matching this schema:\n"
            f"{json.dumps(schema.model_json_schema(), indent=2)}"
        )

        try:
            llm_resp = self._llm.chat.completions.create(
                model=chosen,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": synth_user},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        except Exception as exc:  # noqa: BLE001
            return VendorResponse(
                parsed=None,
                raw={"tavily_results": results},
                citations=citations,
                usage=_zero_usage(),
                latency_ms=_lat(started),
                model=chosen,
                error=f"deepseek error: {type(exc).__name__}: {exc}",
            )

        latency_ms = _lat(started)
        try:
            content = llm_resp.choices[0].message.content or ""
            usage = llm_resp.usage
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
        except Exception as exc:  # noqa: BLE001
            return VendorResponse(
                parsed=None,
                raw={"tavily_results": results},
                citations=citations,
                usage=_zero_usage(),
                latency_ms=latency_ms,
                model=chosen,
                error=f"malformed deepseek response: {exc}",
            )

        cost = estimate_cost(chosen, input_tokens, output_tokens)
        parsed: BaseModel | None = None
        error: str | None = None
        try:
            parsed = schema.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            error = f"parse error: {type(exc).__name__}: {exc}"

        return VendorResponse(
            parsed=parsed,
            raw={"tavily_results": results, "synthesis_content": content},
            citations=citations,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            },
            latency_ms=latency_ms,
            model=chosen,
            error=error,
        )
