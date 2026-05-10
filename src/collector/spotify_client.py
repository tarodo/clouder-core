"""Spotify Web API client with Client Credentials auth and retry semantics."""

from __future__ import annotations

import base64
import json
import random
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from urllib.error import HTTPError, URLError

from .errors import SpotifyAuthError, SpotifyUnavailableError
from .logging_utils import log_event
from .vendor_match.scorer import best_artist_sim, string_sim

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
        tracks: List[Dict[str, Any]],
        correlation_id: str,
        *,
        metadata_fallback_enabled: bool = False,
        title_min: float = 0.90,
        artist_min: float = 0.85,
        duration_tolerance_ms: int = 3000,
    ) -> List[SpotifySearchResult]:
        """Search Spotify for each track by ISRC, with optional metadata fallback.

        Args:
            tracks: list of dicts. Required keys: clouder_track_id, isrc.
                Optional (used by fallback): title, artists, duration_ms.
            correlation_id: trace ID
            metadata_fallback_enabled: if True, fall back to text search on ISRC miss
            title_min, artist_min, duration_tolerance_ms: accept-gate thresholds
        """
        self._ensure_token(correlation_id)
        results: List[SpotifySearchResult] = []
        total = len(tracks)

        for index, track in enumerate(tracks):
            isrc = track["isrc"]
            clouder_track_id = track["clouder_track_id"]
            searched = index + 1

            try:
                spotify_track = self._search_by_isrc(
                    isrc=isrc, correlation_id=correlation_id
                )
            except SpotifyAuthError:
                self._access_token = None
                self._ensure_token(correlation_id)
                spotify_track = self._search_by_isrc(
                    isrc=isrc, correlation_id=correlation_id
                )

            if spotify_track is None and metadata_fallback_enabled:
                title = str(track.get("title") or "").strip()
                artist = str(track.get("artists") or "").strip()
                duration_ms = track.get("duration_ms")
                if title and artist:
                    # Step 1: try sibling ISRCs (off-by-one / off-by-two on last digit).
                    # Cheaper + higher-confidence than metadata text search when
                    # a sibling exists.
                    spotify_track = self._search_by_isrc_neighbours(
                        isrc=isrc,
                        title=title,
                        artist=artist,
                        correlation_id=correlation_id,
                        title_min=title_min,
                        artist_min=artist_min,
                    )
                    if spotify_track is not None:
                        log_event(
                            "INFO",
                            "spotify_isrc_neighbour_match",
                            correlation_id=correlation_id,
                            clouder_track_id=clouder_track_id,
                            isrc=isrc,
                            spotify_id=spotify_track.get("id"),
                            spotify_isrc=spotify_track.get(
                                "external_ids", {}
                            ).get("isrc"),
                            searched=searched,
                            total=total,
                        )
                if spotify_track is None and title and artist:
                    # Step 2: full metadata text search.
                    log_event(
                        "INFO",
                        "spotify_metadata_fallback_attempted",
                        correlation_id=correlation_id,
                        clouder_track_id=clouder_track_id,
                        isrc=isrc,
                        searched=searched,
                        total=total,
                    )
                    metadata_hit = self._search_by_metadata(
                        title=title,
                        artist=artist,
                        duration_ms=int(duration_ms)
                        if isinstance(duration_ms, (int, float))
                        else None,
                        correlation_id=correlation_id,
                        title_min=title_min,
                        artist_min=artist_min,
                        duration_tolerance_ms=duration_tolerance_ms,
                    )
                    if metadata_hit is None:
                        log_event(
                            "INFO",
                            "spotify_metadata_fallback_rejected",
                            correlation_id=correlation_id,
                            clouder_track_id=clouder_track_id,
                            isrc=isrc,
                            searched=searched,
                            total=total,
                        )
                    else:
                        spotify_track, tier = metadata_hit
                        event = (
                            "spotify_metadata_fallback_match"
                            if tier == "strict"
                            else "spotify_metadata_fallback_match_relaxed"
                        )
                        log_event(
                            "INFO",
                            event,
                            correlation_id=correlation_id,
                            clouder_track_id=clouder_track_id,
                            isrc=isrc,
                            spotify_id=spotify_track.get("id"),
                            spotify_isrc=spotify_track.get(
                                "external_ids", {}
                            ).get("isrc"),
                            searched=searched,
                            total=total,
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

            if searched % 25 == 0 or searched == total:
                log_event(
                    "INFO",
                    "spotify_search_progress",
                    correlation_id=correlation_id,
                    searched=searched,
                    total=total,
                )

        return results

    def _search_by_metadata(
        self,
        *,
        title: str,
        artist: str,
        duration_ms: int | None,
        correlation_id: str,
        title_min: float,
        artist_min: float,
        duration_tolerance_ms: int,
    ) -> tuple[Dict[str, Any], str] | None:
        """Spotify text search fallback when ISRC lookup returned no items.

        Builds q=track:<title> artist:<first_artist>, scores each result, and
        returns (best_candidate, tier) where tier is 'strict' or 'relaxed'.
        Strict candidates win over relaxed when both exist. Returns None on
        empty input, no items, or no candidate passing any tier. The query
        uses only the FIRST artist (country-suffix stripped) — Spotify's
        artist: operator substring-matches literally and full BP-shaped
        multi-artist strings often return 0 items.
        """
        if not title.strip() or not artist.strip():
            return None

        query_artist = _first_query_artist(artist) or artist
        q = f"track:{title} artist:{query_artist}"
        params = {"q": q, "type": "track", "limit": "10"}
        url = f"{API_BASE_URL}/search?{urllib.parse.urlencode(params)}"
        payload = self._request(url=url, correlation_id=correlation_id)
        tracks_obj = payload.get("tracks")
        if not isinstance(tracks_obj, dict):
            return None
        items = tracks_obj.get("items")
        if not isinstance(items, list) or not items:
            return None

        strict_best: Dict[str, Any] | None = None
        strict_combined = -1.0
        relaxed_best: Dict[str, Any] | None = None
        relaxed_combined = -1.0
        max_title_sim = 0.0
        max_artist_sim = 0.0
        # Normalize once so both sides shed Radio Edit / Extended Mix / feat. X
        # decoration before the fuzzy match.
        norm_query_title = _normalize_title_for_match(title)
        for item in items:
            if not isinstance(item, dict):
                continue
            cand_name = str(item.get("name") or "")
            cand_artists = tuple(
                str(a.get("name", ""))
                for a in (item.get("artists") or [])
                if isinstance(a, dict)
            )
            cand_duration = item.get("duration_ms")
            cand_duration_ms = (
                int(cand_duration) if isinstance(cand_duration, (int, float)) else None
            )
            norm_cand_name = _normalize_title_for_match(cand_name)
            title_sim = string_sim(norm_cand_name, norm_query_title)
            # Score against the FULL artist list (still want multi-artist
            # collaborations to match symmetrically) — only the search QUERY
            # uses just the first artist.
            artist_sim = best_artist_sim(cand_artists, artist)
            max_title_sim = max(max_title_sim, title_sim)
            max_artist_sim = max(max_artist_sim, artist_sim)
            tier = _match_tier(
                title_sim=title_sim,
                artist_sim=artist_sim,
                candidate_duration_ms=cand_duration_ms,
                query_duration_ms=duration_ms,
                title_min=title_min,
                artist_min=artist_min,
                duration_tolerance_ms=duration_tolerance_ms,
            )
            combined = title_sim + artist_sim
            if tier == "strict" and combined > strict_combined:
                strict_combined = combined
                strict_best = item
            elif tier == "relaxed" and combined > relaxed_combined:
                relaxed_combined = combined
                relaxed_best = item
        if strict_best is not None:
            return strict_best, "strict"
        if relaxed_best is not None:
            return relaxed_best, "relaxed"
        log_event(
            "INFO",
            "spotify_metadata_fallback_scores",
            correlation_id=correlation_id,
            title_sim=round(max_title_sim, 3),
            artist_sim=round(max_artist_sim, 3),
            candidate_count=len(items),
        )
        return None

    def _search_by_isrc_neighbours(
        self,
        *,
        isrc: str,
        title: str,
        artist: str,
        correlation_id: str,
        title_min: float,
        artist_min: float,
    ) -> Dict[str, Any] | None:
        """Try ISRCs that differ from the query by ±1, ±2 in the last digit.

        Sibling ISRCs in the same release are common when Beatport ships an
        ISRC that's off-by-one from Spotify's master. Each candidate is
        verified against title/artist gates (NO duration check — radio edits
        and master/extended versions can differ wildly in length but are
        legitimately the same track family). Closest neighbour wins on tie.
        Title is normalized via _normalize_title_for_match.
        """
        neighbours = _isrc_neighbours(isrc)
        if not neighbours:
            return None
        norm_query_title = _normalize_title_for_match(title)
        for nb in neighbours:
            track = self._search_by_isrc(isrc=nb, correlation_id=correlation_id)
            if track is None:
                continue
            cand_name = str(track.get("name") or "")
            cand_artists = tuple(
                str(a.get("name", ""))
                for a in (track.get("artists") or [])
                if isinstance(a, dict)
            )
            title_sim = string_sim(
                _normalize_title_for_match(cand_name), norm_query_title
            )
            artist_sim = best_artist_sim(cand_artists, artist)
            if title_sim < title_min or artist_sim < artist_min:
                continue
            return track
        return None

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


_COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Za-z]{2,4}\)\s*$")


def _first_query_artist(artists: str) -> str:
    """Pick the first artist for Spotify's `artist:` search operator.

    Spotify's artist filter substring-matches the literal query against each
    candidate artist string; passing the BP-shaped multi-artist string
    (`Kays (UK), Nixxy Rain`) often returns 0 items because it doesn't appear
    verbatim. Use just the first artist (split on `,` or `&`) and strip the
    trailing country tag (`(UK)`, `(USA)`, etc.).
    """
    if not artists or not artists.strip():
        return ""
    first = re.split(r"[,&]", artists, maxsplit=1)[0].strip()
    first = _COUNTRY_SUFFIX_RE.sub("", first).strip()
    return first


def _isrc_neighbours(isrc: str) -> list[str]:
    """Generate sibling ISRCs by varying the last digit ±1, ±2.

    Beatport sometimes emits ISRCs that differ from Spotify's master by a
    single digit at the tail (off-by-one releases / different masters).
    Order is closest-first: +1, -1, +2, -2. Out-of-range (negative or > 9)
    is skipped so we never carry into the prior digit. Returns [] if the
    last char is not a digit.
    """
    if not isrc or not isrc[-1].isdigit():
        return []
    last = int(isrc[-1])
    prefix = isrc[:-1]
    out: list[str] = []
    for delta in (1, -1, 2, -2):
        new = last + delta
        if 0 <= new <= 9:
            out.append(f"{prefix}{new}")
    return out


# Suffix patterns commonly appended by labels — strip before fuzzy matching.
# Order matters: more specific patterns first.
_TITLE_SUFFIX_PATTERNS = [
    # "(feat. X)" / "[feat. X]" / " - feat. X" / " feat. X"
    re.compile(r"[\s]*[\(\[\-][\s]*(feat\.?|ft\.?|featuring)[\s].*?[\)\]]", re.IGNORECASE),
    re.compile(r"[\s]+(feat\.?|ft\.?|featuring)[\s].*$", re.IGNORECASE),
    # "(... Mix)", "[... Mix]", " - ... Mix"
    re.compile(r"[\s]*[\(\[][^()\[\]]*\b(remix|mix|edit|version|dub|bootleg|rework|vip)\b[^()\[\]]*[\)\]]", re.IGNORECASE),
    re.compile(r"[\s]*\-[\s]+[^-]*\b(radio edit|extended mix|original mix|club mix|dub mix|remix|edit|vip)\b.*$", re.IGNORECASE),
]


def _normalize_title_for_match(title: str) -> str:
    """Lowercase + strip common suffixes (Radio Edit / Extended Mix / feat. X /
    Remix in brackets) so fuzzy comparison sees the canonical title."""
    if not title:
        return ""
    s = title
    for pat in _TITLE_SUFFIX_PATTERNS:
        s = pat.sub("", s)
    return " ".join(s.lower().split())


# Title/artist similarity gates — when both >= this, accept even if duration
# diverges (typical: master vs radio edit / extended of the SAME track).
_RELAXED_TITLE_MIN = 0.95
_RELAXED_ARTIST_MIN = 0.95


def _match_tier(
    *,
    title_sim: float,
    artist_sim: float,
    candidate_duration_ms: int | None,
    query_duration_ms: int | None,
    title_min: float,
    artist_min: float,
    duration_tolerance_ms: int,
) -> str:
    """Classify a candidate against per-component fuzzy gates.

    Returns:
        'strict'  — passes title_min + artist_min + duration tolerance
                    (or duration unknown on either side)
        'relaxed' — passes title_min + artist_min, fails duration, but
                    title_sim >= 0.95 AND artist_sim >= 0.95 (near-perfect
                    text → same track, different master)
        'fail'    — does not pass min thresholds OR fails duration without
                    near-perfect text backup
    """
    if title_sim < title_min:
        return "fail"
    if artist_sim < artist_min:
        return "fail"
    if candidate_duration_ms is None or query_duration_ms is None:
        return "strict"
    if abs(candidate_duration_ms - query_duration_ms) <= duration_tolerance_ms:
        return "strict"
    if title_sim >= _RELAXED_TITLE_MIN and artist_sim >= _RELAXED_ARTIST_MIN:
        return "relaxed"
    return "fail"
