"""Spotify Web API client with Client Credentials auth and retry semantics."""

from __future__ import annotations

import base64
import json
import random
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from urllib.error import HTTPError, URLError

from .errors import SpotifyAuthError, SpotifyUnavailableError
from .logging_utils import log_event

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE_URL = "https://api.spotify.com/v1"


@dataclass(frozen=True)
class SpotifySearchResult:
    isrc: str
    clouder_track_id: str
    spotify_track: dict | None
    spotify_id: str | None


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 15.0,
        max_retries: int = 4,
        backoff_base_seconds: float = 0.5,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.sleep_fn = sleep_fn
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def search_tracks_by_isrc(
        self,
        tracks: List[Dict[str, str]],
        correlation_id: str,
    ) -> List[SpotifySearchResult]:
        """Search Spotify for each track by ISRC.

        Args:
            tracks: list of {"clouder_track_id": ..., "isrc": ...}
            correlation_id: request trace ID

        Returns:
            List of SpotifySearchResult for each input track.
        """
        self._ensure_token(correlation_id)
        results: List[SpotifySearchResult] = []

        for index, track in enumerate(tracks):
            isrc = track["isrc"]
            clouder_track_id = track["clouder_track_id"]

            try:
                spotify_track = self._search_by_isrc(
                    isrc=isrc, correlation_id=correlation_id
                )
                spotify_id = spotify_track["id"] if spotify_track else None
                results.append(
                    SpotifySearchResult(
                        isrc=isrc,
                        clouder_track_id=clouder_track_id,
                        spotify_track=spotify_track,
                        spotify_id=spotify_id,
                    )
                )
            except SpotifyAuthError:
                # Token might have expired mid-batch; re-authenticate once.
                self._access_token = None
                self._ensure_token(correlation_id)
                spotify_track = self._search_by_isrc(
                    isrc=isrc, correlation_id=correlation_id
                )
                spotify_id = spotify_track["id"] if spotify_track else None
                results.append(
                    SpotifySearchResult(
                        isrc=isrc,
                        clouder_track_id=clouder_track_id,
                        spotify_track=spotify_track,
                        spotify_id=spotify_id,
                    )
                )

            if (index + 1) % 100 == 0:
                log_event(
                    "INFO",
                    "spotify_search_progress",
                    correlation_id=correlation_id,
                    searched=index + 1,
                    total=len(tracks),
                )

        return results

    def _search_by_isrc(
        self, isrc: str, correlation_id: str
    ) -> Dict[str, Any] | None:
        """Search Spotify for a single track by ISRC.

        Fetches up to 10 results and returns the earliest by release date.
        """
        params = {
            "q": f"isrc:{isrc}",
            "type": "track",
            "limit": "10",
        }
        url = f"{API_BASE_URL}/search?{urllib.parse.urlencode(params)}"
        payload = self._request(url=url, correlation_id=correlation_id)
        tracks_obj = payload.get("tracks")
        if not isinstance(tracks_obj, dict):
            return None
        items = tracks_obj.get("items")
        if not isinstance(items, list) or not items:
            return None
        valid = [t for t in items if isinstance(t, dict)]
        if not valid:
            return None
        if len(valid) == 1:
            return valid[0]
        return min(valid, key=_album_release_sort_key)

    def _ensure_token(self, correlation_id: str) -> None:
        """Authenticate or reuse cached token."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return
        self._authenticate(correlation_id)

    def _authenticate(self, correlation_id: str) -> None:
        """Obtain access token via Client Credentials flow."""
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body = "grant_type=client_credentials".encode("utf-8")

        log_event(
            "INFO",
            "spotify_auth_request",
            correlation_id=correlation_id,
        )

        request = urllib.request.Request(
            url=TOKEN_URL, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SpotifyAuthError(
                f"Spotify token request failed: {exc}"
            ) from exc

        access_token = parsed.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SpotifyAuthError("Spotify token response missing access_token")

        expires_in = int(parsed.get("expires_in", 3600))
        self._access_token = access_token
        # Refresh 60 seconds before actual expiry.
        self._token_expires_at = time.monotonic() + max(expires_in - 60, 60)

        log_event(
            "INFO",
            "spotify_auth_success",
            correlation_id=correlation_id,
            expires_in=expires_in,
        )

    def _request(self, url: str, correlation_id: str) -> Dict[str, Any]:
        """Execute a GET request to Spotify API with retry logic."""
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                url=url, method="GET", headers=headers
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    raw = response.read().decode("utf-8")
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        raise SpotifyUnavailableError(
                            "Unexpected Spotify payload type"
                        )
                    return parsed
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise SpotifyAuthError(
                        f"Spotify API returned HTTP {exc.code}"
                    ) from exc

                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(retry_after) if retry_after else None
                    if delay and attempt < self.max_retries:
                        log_event(
                            "INFO",
                            "spotify_rate_limited",
                            correlation_id=correlation_id,
                            retry_after=delay,
                            attempt=attempt + 1,
                        )
                        self.sleep_fn(delay)
                        continue

                if exc.code in TRANSIENT_STATUS_CODES and attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue

                raise SpotifyUnavailableError(
                    f"Spotify API returned HTTP {exc.code}"
                ) from exc
            except (URLError, TimeoutError, ValueError) as exc:
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise SpotifyUnavailableError(
                    "Spotify API request failed after retries"
                ) from exc

        raise SpotifyUnavailableError("Spotify API request failed")

    def _sleep_backoff(self, attempt: int) -> None:
        jitter = random.uniform(0.0, 0.25)
        delay = self.backoff_base_seconds * (2**attempt) + jitter
        self.sleep_fn(delay)


def _album_release_sort_key(track: Dict[str, Any]) -> str:
    """Extract a sortable release date string from a Spotify track.

    Spotify release_date can be "YYYY", "YYYY-MM", or "YYYY-MM-DD".
    Pad to "YYYY-MM-DD" so shorter dates sort earliest (e.g. "2020" -> "2020-00-00").
    """
    album = track.get("album")
    if not isinstance(album, dict):
        return "9999-99-99"
    date = album.get("release_date")
    if not isinstance(date, str) or not date:
        return "9999-99-99"
    parts = date.split("-")
    while len(parts) < 3:
        parts.append("00")
    return "-".join(parts[:3])
