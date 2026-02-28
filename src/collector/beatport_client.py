"""Beatport API client with pagination and retry semantics."""

from __future__ import annotations

import json
import random
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError

from .errors import UpstreamAuthError, UpstreamUnavailableError


TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def is_retryable_status(status_code: int) -> bool:
    return status_code in TRANSIENT_STATUS_CODES


class BeatportClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 15.0,
        max_retries: int = 4,
        backoff_base_seconds: float = 0.5,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.sleep_fn = sleep_fn

    def fetch_weekly_releases(
        self,
        bp_token: str,
        style_id: int,
        week_start: str,
        week_end: str,
        correlation_id: str,
    ) -> Tuple[List[Dict[str, Any]], int]:
        page = 1
        max_pages = 300
        all_items: List[Dict[str, Any]] = []
        pages_fetched = 0

        while page <= max_pages:
            payload = self._request_page(
                bp_token=bp_token,
                style_id=style_id,
                week_start=week_start,
                week_end=week_end,
                page=page,
                correlation_id=correlation_id,
            )
            pages_fetched += 1

            items = self._extract_items(payload)
            all_items.extend(items)

            if not self._has_next_page(payload, page):
                return all_items, pages_fetched

            page += 1

        raise UpstreamUnavailableError("Beatport pagination exceeded safety limit")

    def _request_page(
        self,
        bp_token: str,
        style_id: int,
        week_start: str,
        week_end: str,
        page: int,
        correlation_id: str,
    ) -> Dict[str, Any]:
        params = {
            "style_id": str(style_id),
            "week_start": week_start,
            "week_end": week_end,
            "page": str(page),
        }
        url = f"{self.base_url}/releases?{urllib.parse.urlencode(params)}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {bp_token}",
            "X-Correlation-ID": correlation_id,
        }

        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(url=url, method="GET", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        raise UpstreamUnavailableError("Unexpected Beatport payload type")
                    return parsed
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise UpstreamAuthError() from exc

                if is_retryable_status(exc.code) and attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue

                raise UpstreamUnavailableError(f"Beatport API returned HTTP {exc.code}") from exc
            except (URLError, TimeoutError, ValueError) as exc:
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise UpstreamUnavailableError("Beatport API request failed after retries") from exc

        raise UpstreamUnavailableError("Beatport API request failed")

    def _sleep_backoff(self, attempt: int) -> None:
        jitter = random.uniform(0.0, 0.25)
        delay = self.backoff_base_seconds * (2**attempt) + jitter
        self.sleep_fn(delay)

    @staticmethod
    def _extract_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidate_keys = ("results", "items", "releases", "data")
        for key in candidate_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _has_next_page(payload: Dict[str, Any], current_page: int) -> bool:
        direct_next = payload.get("next")
        if direct_next:
            return True

        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            if pagination.get("has_next") is True:
                return True
            total_pages = pagination.get("total_pages")
            if isinstance(total_pages, int):
                return current_page < total_pages

        next_page = payload.get("next_page")
        if isinstance(next_page, int):
            return next_page > current_page

        return False
