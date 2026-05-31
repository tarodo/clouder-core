"""Authenticated ytmusicapi wrapper for playlist publish.

Single point of impact if Google changes the YouTube Music internal API.
Construct via build_authenticated_ytmusic(); inject a fake `yt` in tests.
"""

from __future__ import annotations

from typing import Any

from . import YtmusicApiError, YtmusicNotFoundError

_CHUNK = 100


def build_authenticated_ytmusic(token_dict: dict, client_id: str, client_secret: str):
    """Build an authenticated ytmusicapi.YTMusic from a token dict."""
    from ytmusicapi import YTMusic

    try:
        from ytmusicapi import OAuthCredentials
    except ImportError:  # pragma: no cover - layout fallback
        from ytmusicapi.auth.oauth import OAuthCredentials

    return YTMusic(
        auth=token_dict,
        oauth_credentials=OAuthCredentials(
            client_id=client_id, client_secret=client_secret
        ),
    )


class YtmusicUserClient:
    def __init__(self, *, yt: Any) -> None:
        self._yt = yt

    def create_playlist(self, *, name: str, description: str | None, privacy: str) -> str:
        try:
            result = self._yt.create_playlist(
                name, description or "", privacy_status=privacy
            )
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc
        if not isinstance(result, str):
            raise YtmusicApiError(f"create_playlist failed: {result!r}")
        return result

    def edit_meta(self, *, playlist_id: str, name: str, description: str | None, privacy: str) -> None:
        try:
            self._yt.edit_playlist(
                playlist_id, title=name, description=description or "",
                privacyStatus=privacy,
            )
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc

    def get_existing_items(self, playlist_id: str) -> list[dict]:
        try:
            playlist = self._yt.get_playlist(playlist_id, limit=None)
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc
        items: list[dict] = []
        for track in (playlist or {}).get("tracks", []) or []:
            vid = track.get("videoId")
            set_vid = track.get("setVideoId")
            if vid and set_vid:
                items.append({"videoId": vid, "setVideoId": set_vid})
        return items

    def add_items(self, playlist_id: str, video_ids: list[str]) -> None:
        for i in range(0, len(video_ids), _CHUNK):
            chunk = video_ids[i : i + _CHUNK]
            if not chunk:
                continue
            try:
                self._yt.add_playlist_items(playlist_id, chunk, duplicates=True)
            except Exception as exc:  # noqa: BLE001
                raise self._classify(exc) from exc

    def remove_items(self, playlist_id: str, items: list[dict]) -> None:
        if not items:
            return
        try:
            self._yt.remove_playlist_items(playlist_id, items)
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc

    @staticmethod
    def _classify(exc: Exception) -> YtmusicApiError:
        msg = str(exc).lower()
        if "not found" in msg or "404" in msg or "does not exist" in msg:
            return YtmusicNotFoundError(str(exc))
        return YtmusicApiError(str(exc))
