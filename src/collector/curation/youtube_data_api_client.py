"""YouTube Data API v3 client for playlist publish.

ytmusicapi's OAuth (device-flow) path is broken upstream for write operations
— YouTube Music returns HTTP 400 "Request contains an invalid argument" for
create/add via OAuth (ytmusicapi #676/#921). We therefore publish via the
official YouTube Data API v3, reusing the SAME Google OAuth bearer token and
``youtube`` scope. Plain REST over a requests session; inject a fake session
in tests. Exposes the same interface YtmusicPublishService expects.
"""

from __future__ import annotations

import json
from typing import Any

from . import YtmusicApiError, YtmusicNotAuthorizedError, YtmusicNotFoundError

_BASE = "https://www.googleapis.com/youtube/v3"
_UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"
_PRIVACY = {"PUBLIC": "public", "PRIVATE": "private", "UNLISTED": "unlisted"}
_COVER_BOUNDARY = "clouder_ytmusic_cover_boundary"
# snippet.type has no documented enum in the API reference; "hero" is the
# best-known value for the playlist banner image. A wrong value (or any cover
# error) is contained by the caller's cover_failed fallback and the YouTube
# message is logged so the value can be corrected from prod evidence.
_COVER_TYPE = "hero"
_PNG_MAGIC = b"\x89PNG"


class YoutubeDataApiClient:
    """Mirrors the YtmusicPublishService client contract using Data API v3.

    ``get_existing_items`` returns playlistItem ids (opaque to the service);
    ``remove_items`` deletes by those ids.
    """

    def __init__(self, *, access_token: str, session: Any) -> None:
        self._token = access_token
        self._session = session

    def create_playlist(self, *, name: str, description: str | None, privacy: str) -> str:
        body = {
            "snippet": {"title": name, "description": description or ""},
            "status": {"privacyStatus": _PRIVACY.get(privacy, "private")},
        }
        data = self._request(
            "POST", f"{_BASE}/playlists",
            params={"part": "snippet,status"}, json_body=body,
        )
        pid = data.get("id")
        if not isinstance(pid, str):
            raise YtmusicApiError(f"playlists.insert returned no id: {data!r}")
        return pid

    def edit_meta(self, *, playlist_id: str, name: str, description: str | None, privacy: str) -> None:
        body = {
            "id": playlist_id,
            "snippet": {"title": name, "description": description or ""},
            "status": {"privacyStatus": _PRIVACY.get(privacy, "private")},
        }
        self._request(
            "PUT", f"{_BASE}/playlists",
            params={"part": "snippet,status"}, json_body=body,
        )

    def get_existing_items(self, playlist_id: str) -> list[str]:
        item_ids: list[str] = []
        page_token: str | None = None
        while True:
            params = {"part": "id", "playlistId": playlist_id, "maxResults": "50"}
            if page_token:
                params["pageToken"] = page_token
            data = self._request("GET", f"{_BASE}/playlistItems", params=params)
            for item in data.get("items", []):
                if item.get("id"):
                    item_ids.append(item["id"])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return item_ids

    def remove_items(self, playlist_id: str, items: list[str]) -> None:
        for item_id in items:
            self._request("DELETE", f"{_BASE}/playlistItems", params={"id": item_id})

    def add_items(self, playlist_id: str, video_ids: list[str]) -> None:
        # Data API v3 has no bulk insert: one playlistItems.insert per video.
        for video_id in video_ids:
            body = {
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            }
            self._request(
                "POST", f"{_BASE}/playlistItems",
                params={"part": "snippet"}, json_body=body,
            )

    def set_cover(self, playlist_id: str, image_bytes: bytes) -> None:
        """Set a custom playlist cover via playlistImages.insert (multipart
        media upload). YouTube requires a square (1:1) JPEG/PNG <= 2 MB."""
        content_type = "image/png" if image_bytes[:8].startswith(_PNG_MAGIC) else "image/jpeg"
        metadata = json.dumps(
            {"snippet": {"playlistId": playlist_id, "type": _COVER_TYPE}}
        )
        body = (
            f"--{_COVER_BOUNDARY}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{_COVER_BOUNDARY}\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + image_bytes + f"\r\n--{_COVER_BOUNDARY}--\r\n".encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": f"multipart/related; boundary={_COVER_BOUNDARY}",
            "Accept": "application/json",
        }
        resp = self._session.request(
            method="POST",
            url=f"{_UPLOAD_BASE}/playlistImages",
            params={"part": "snippet", "uploadType": "multipart"},
            data=body,
            headers=headers,
        )
        status = getattr(resp, "status_code", 0)
        if not (200 <= status < 300):
            raise YtmusicApiError(f"YouTube {status}: {self._error_message(resp)}")

    # ---------- core HTTP ----------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        body = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(json_body)
        resp = self._session.request(
            method=method, url=url, params=params, data=body, headers=headers,
        )
        status = getattr(resp, "status_code", 0)
        if 200 <= status < 300:
            try:
                return resp.json()
            except Exception:
                return {}
        if status == 401:
            raise YtmusicNotAuthorizedError("YouTube returned 401 (token rejected)")
        if status == 404:
            raise YtmusicNotFoundError(f"YouTube 404: {url}")
        raise YtmusicApiError(f"YouTube {status}: {self._error_message(resp)}")

    @staticmethod
    def _error_message(resp: Any) -> str:
        try:
            err = (resp.json() or {}).get("error") or {}
            if isinstance(err, dict):
                return err.get("message") or "request failed"
        except Exception:
            pass
        return "request failed"
