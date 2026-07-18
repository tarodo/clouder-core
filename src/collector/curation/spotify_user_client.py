"""User-OAuth Spotify Web API client (playlist publish, import).

Distinct from collector.spotify_client which uses client_credentials.
Retry policy: 429 → respect Retry-After once; 5xx → 1 retry; 401 → no
retry, surfaces as SpotifyNotAuthorizedError; 403 with
'insufficient_scope' → SpotifyScopeInsufficientError.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable

from . import (
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyNotFoundError,
    SpotifyRateLimitedError,
    SpotifyScopeInsufficientError,
)


_BASE = "https://api.spotify.com/v1"
_MAX_RETRIES_429 = 1
_MAX_RETRIES_5XX = 1


@dataclass(frozen=True)
class SpotifyArtistRef:
    id: str
    name: str
    spotify_id: str | None = None


@dataclass(frozen=True)
class SpotifyTrackPayload:
    id: str
    name: str
    duration_ms: int | None
    isrc: str | None
    artists: tuple[SpotifyArtistRef, ...]


@dataclass(frozen=True)
class SpotifyPlaylistRef:
    id: str
    url: str | None


def _track_payload(body: dict) -> SpotifyTrackPayload:
    return SpotifyTrackPayload(
        id=body["id"],
        name=body.get("name") or "",
        duration_ms=body.get("duration_ms"),
        isrc=(body.get("external_ids") or {}).get("isrc"),
        artists=tuple(
            SpotifyArtistRef(
                id=a.get("id") or "", name=a.get("name") or "",
                spotify_id=a.get("id"),
            )
            for a in (body.get("artists") or [])
        ),
    )


class SpotifyUserClient:
    def __init__(
        self,
        *,
        access_token: str,
        session: Any,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._access_token = access_token
        self._session = session
        self._sleep = sleep or (lambda s: None)

    # ---------- Public methods ----------------------------------------------

    def get_track(self, spotify_id: str) -> SpotifyTrackPayload:
        return _track_payload(self._request("GET", f"{_BASE}/tracks/{spotify_id}"))

    def get_playlist_name(self, spotify_playlist_id: str) -> str:
        body = self._request(
            "GET", f"{_BASE}/playlists/{spotify_playlist_id}?fields=name",
        )
        return body.get("name") or ""

    def get_playlist_tracks(
        self, spotify_playlist_id: str, *, limit: int,
    ) -> list[SpotifyTrackPayload]:
        out: list[SpotifyTrackPayload] = []
        offset = 0
        page_size = 100
        while len(out) < limit:
            body = self._request(
                "GET",
                f"{_BASE}/playlists/{spotify_playlist_id}/tracks"
                f"?limit={page_size}&offset={offset}",
            )
            items = body.get("items") or []
            for item in items:
                track = item.get("track")
                if not track:
                    continue
                if track.get("is_local"):
                    continue
                if track.get("type") == "episode":
                    continue
                if not track.get("id"):
                    continue
                out.append(_track_payload(track))
                if len(out) >= limit:
                    break
            if body.get("next") is None:
                break
            offset += page_size
        return out

    def create_playlist(
        self,
        *,
        user_spotify_id: str,
        name: str,
        description: str | None,
        public: bool,
    ) -> SpotifyPlaylistRef:
        body = self._request(
            "POST",
            f"{_BASE}/users/{user_spotify_id}/playlists",
            json_body={
                "name": name,
                "description": description or "",
                "public": public,
            },
        )
        return SpotifyPlaylistRef(
            id=body["id"],
            url=(body.get("external_urls") or {}).get("spotify"),
        )

    def update_playlist(
        self,
        *,
        spotify_playlist_id: str,
        name: str,
        description: str | None,
        public: bool,
    ) -> None:
        self._request(
            "PUT",
            f"{_BASE}/playlists/{spotify_playlist_id}",
            json_body={
                "name": name,
                "description": description or "",
                "public": public,
            },
        )

    def replace_tracks(
        self, spotify_playlist_id: str, uris: list[str]
    ) -> None:
        self._request(
            "PUT",
            f"{_BASE}/playlists/{spotify_playlist_id}/tracks",
            json_body={"uris": uris},
        )

    def append_tracks(
        self, spotify_playlist_id: str, uris: list[str]
    ) -> None:
        if not uris:
            return
        self._request(
            "POST",
            f"{_BASE}/playlists/{spotify_playlist_id}/tracks",
            json_body={"uris": uris},
        )

    def set_cover(self, spotify_playlist_id: str, jpeg_bytes: bytes) -> None:
        encoded = base64.b64encode(jpeg_bytes)
        self._request(
            "PUT",
            f"{_BASE}/playlists/{spotify_playlist_id}/images",
            data=encoded,
            content_type="image/jpeg",
        )

    # ---------- Core HTTP w/ retry ------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict | None = None,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": content_type,
        }
        body: Any = None
        if json_body is not None:
            body = json.dumps(json_body)
        elif data is not None:
            body = data

        attempts_429 = 0
        attempts_5xx = 0
        while True:
            resp = self._session.request(
                method=method, url=url, headers=headers, data=body,
            )
            status = getattr(resp, "status_code", 0)
            if 200 <= status < 300:
                try:
                    return resp.json()
                except Exception:
                    return {}
            if status == 401:
                raise SpotifyNotAuthorizedError("Spotify returned 401")
            if status == 403:
                msg = ""
                try:
                    err = resp.json().get("error") or {}
                    msg = err.get("message", "") if isinstance(err, dict) else ""
                except Exception:
                    pass
                if "scope" in msg.lower():
                    raise SpotifyScopeInsufficientError(msg or "Insufficient scope")
                raise SpotifyApiError(f"Spotify 403: {msg or 'forbidden'}")
            if status == 429:
                if attempts_429 >= _MAX_RETRIES_429:
                    raise SpotifyRateLimitedError("Spotify rate limit persists")
                retry_after = float(
                    (resp.headers or {}).get("Retry-After") or "0.0"
                )
                self._sleep(retry_after)
                attempts_429 += 1
                continue
            if 500 <= status < 600:
                if attempts_5xx >= _MAX_RETRIES_5XX:
                    raise SpotifyApiError(f"Spotify {status}")
                self._sleep(0.5)
                attempts_5xx += 1
                continue
            if status == 404:
                raise SpotifyNotFoundError(f"Spotify 404: {url}")
            raise SpotifyApiError(
                f"Spotify {status}: unexpected response"
            )
