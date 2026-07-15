"""Thin Tavily REST wrapper (stdlib only) with deterministic credit counting.

Pricing model (spec + owner's plan): basic search = 1 credit,
extract = 1 credit per <=5 URLs, $8 per 1000 credits.
"""

from __future__ import annotations

import json
import math
import urllib.request
from typing import Callable


def _default_post(api_key_holder: dict) -> Callable[[str, dict], dict]:
    def post(path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"https://api.tavily.com/{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.load(resp)
    return post


class TavilyClient:
    def __init__(self, api_key: str, post: Callable[[str, dict], dict] | None = None):
        self._api_key = api_key
        self._post = post or _default_post({})
        self._credits = 0

    @property
    def credits_used(self) -> int:
        return self._credits

    def search(
        self,
        query: str,
        *,
        max_results: int = 8,
        include_raw_content: bool = False,
        include_domains: list[str] | None = None,
    ) -> dict:
        payload: dict = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        self._credits += 1
        return self._post("search", payload)

    def extract(self, urls: list[str]) -> dict:
        if not urls:
            return {"results": []}
        self._credits += math.ceil(len(urls) / 5)
        return self._post("extract", {"api_key": self._api_key, "urls": urls})
