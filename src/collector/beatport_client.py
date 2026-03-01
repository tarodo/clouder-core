"""Beatport API client with pagination and retry semantics."""

from __future__ import annotations

import json
import random
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Tuple
from urllib.error import HTTPError, URLError

from .errors import UpstreamAuthError, UpstreamUnavailableError
from .logging_utils import log_event

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
        max_pages = 300
        all_items: List[Dict[str, Any]] = []
        pages_fetched = 0
        url = f"{self.base_url}/tracks/"
        params: Dict[str, str] = {
            "genre_id": str(style_id),
            "publish_date": f"{week_start}:{week_end}",
            "page": "1",
            "per_page": "100",
            "order_by": "-publish_date",
        }

        while pages_fetched < max_pages:
            payload = self._request_page(
                url=url,
                params=params,
                bp_token=bp_token,
                correlation_id=correlation_id,
            )
            pages_fetched += 1

            items = self._extract_items(payload)
            all_items.extend(items)

            next_url = payload.get("next")
            if not isinstance(next_url, str) or not next_url.strip():
                return all_items, pages_fetched

            params = self._extract_params_for_requests(next_url)
            if not params:
                raise UpstreamUnavailableError("Beatport pagination link is malformed")

        raise UpstreamUnavailableError("Beatport pagination exceeded safety limit")

    def _request_page(
        self,
        url: str,
        params: Dict[str, str],
        bp_token: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        request_url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {bp_token}",
            "X-Correlation-ID": correlation_id,
        }

        for attempt in range(self.max_retries + 1):
            log_event(
                "INFO",
                "beatport_request",
                correlation_id=correlation_id,
                beatport_url=request_url,
                beatport_page=params.get("page"),
                beatport_attempt=attempt + 1,
            )
            request = urllib.request.Request(
                url=request_url, method="GET", headers=headers
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    log_event(
                        "INFO",
                        "beatport_response",
                        correlation_id=correlation_id,
                        beatport_url=request_url,
                        beatport_page=params.get("page"),
                        beatport_attempt=attempt + 1,
                        beatport_http_status=getattr(response, "status", 200),
                    )
                    raw = response.read().decode("utf-8")
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        raise UpstreamUnavailableError(
                            "Unexpected Beatport payload type"
                        )
                    return parsed
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise UpstreamAuthError() from exc

                if is_retryable_status(exc.code) and attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue

                raise UpstreamUnavailableError(
                    f"Beatport API returned HTTP {exc.code}"
                ) from exc
            except (URLError, TimeoutError, ValueError) as exc:
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise UpstreamUnavailableError(
                    "Beatport API request failed after retries"
                ) from exc

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
    def _extract_params_for_requests(url: str) -> Dict[str, str]:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        return {key: values[0] for key, values in params.items() if values}
