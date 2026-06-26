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

from collector.logging_utils import log_event

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

    def __init__(
        self, *, access_token: str, session: Any, correlation_id: str | None = None
    ) -> None:
        self._token = access_token
        self._session = session
        self._correlation_id = correlation_id

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

    def get_existing_items(self, playlist_id: str) -> list[dict]:
        """Return [{videoId, itemId}] in playlist order. videoId is used to
        diff against the desired set; itemId is the playlistItem id needed for
        removal. ``part=snippet`` carries resourceId.videoId (list = 1 unit)."""
        items: list[dict] = []
        page_token: str | None = None
        while True:
            params = {"part": "snippet", "playlistId": playlist_id, "maxResults": "50"}
            if page_token:
                params["pageToken"] = page_token
            data = self._request("GET", f"{_BASE}/playlistItems", params=params)
            for item in data.get("items", []):
                video_id = ((item.get("snippet") or {}).get("resourceId") or {}).get("videoId")
                if item.get("id") and video_id:
                    items.append({"videoId": video_id, "itemId": item["id"]})
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

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

    def move_item(self, playlist_id: str, item_id: str, video_id: str, position: int) -> None:
        # Reorder one playlistItem to an absolute index (50 quota units).
        # YouTube shifts the other items to accommodate the new position.
        body = {
            "id": item_id,
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
                "position": position,
            },
        }
        self._request(
            "PUT", f"{_BASE}/playlistItems",
            params={"part": "snippet"}, json_body=body,
        )

    def set_cover(self, playlist_id: str, image_bytes: bytes) -> None:
        """Set/replace a custom playlist cover. Tries playlistImages.insert
        (POST); if that fails for a reason other than auth (most commonly the
        playlist already has an image), retries playlistImages.update (PUT) on
        the same media-upload endpoint. Raises only if both fail."""
        insert_resp = self._upload_cover("POST", playlist_id, image_bytes)
        insert_status = getattr(insert_resp, "status_code", 0)
        if 200 <= insert_status < 300:
            return
        if insert_status == 401:
            raise YtmusicNotAuthorizedError("YouTube returned 401 (token rejected)")
        update_resp = self._upload_cover("PUT", playlist_id, image_bytes)
        update_status = getattr(update_resp, "status_code", 0)
        if 200 <= update_status < 300:
            return
        message, reason = self._error_detail(update_resp)
        reason_tag = f" [{reason}]" if reason else ""
        raise YtmusicApiError(
            f"YouTube cover insert {insert_status} / update {update_status}"
            f"{reason_tag}: {message}",
            status_code=update_status, reason=reason,
        )

    def _upload_cover(self, method: str, playlist_id: str, image_bytes: bytes) -> Any:
        """Build the multipart/related body and send it with the given HTTP
        method (POST = insert, PUT = update). YouTube requires a square (1:1)
        JPEG/PNG <= 2 MB."""
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
        return self._session.request(
            method=method,
            url=f"{_UPLOAD_BASE}/playlistImages",
            params={"part": "snippet", "uploadType": "multipart"},
            data=body,
            headers=headers,
        )

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

        message, reason = self._error_detail(resp)
        endpoint = url.rsplit("/", 1)[-1] or url
        detail = (
            f"YouTube {status} [{reason}] on {method} {endpoint}: {message}"
            if reason
            else f"YouTube {status} on {method} {endpoint}: {message}"
        )
        # Breadcrumb so the failing call is queryable in CloudWatch even when the
        # caller swallows the error (cover fallback). No token/body is logged.
        log_event(
            "WARNING", "ytmusic_api_call_failed",
            correlation_id=self._correlation_id,
            status_code=status, reason=reason,
            phase=f"{method} {endpoint}", error_message=message,
        )
        if status == 401:
            raise YtmusicNotAuthorizedError(detail)
        if status == 404:
            raise YtmusicNotFoundError(detail, status_code=status, reason=reason)
        raise YtmusicApiError(detail, status_code=status, reason=reason)

    @staticmethod
    def _error_detail(resp: Any) -> tuple[str, str | None]:
        """Pull (human message, machine reason) from a Google API error body.
        ``reason`` comes from ``error.errors[0].reason`` (or ``.domain``), with
        ``error.status`` as a last resort — this is the field that distinguishes
        a transient 409 (SERVICE_UNAVAILABLE/ABORTED) from a hard conflict."""
        try:
            err = (resp.json() or {}).get("error") or {}
        except Exception:
            return "request failed", None
        if not isinstance(err, dict):
            return "request failed", None
        message = err.get("message") or "request failed"
        reason: str | None = None
        errors = err.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            reason = errors[0].get("reason") or errors[0].get("domain")
        if reason is None and isinstance(err.get("status"), str):
            reason = err["status"]
        return message, reason
