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
import time
from typing import Any, Callable

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

# Transient-failure retry. Prod evidence (PR #191 instrumentation): a single
# playlistItems.insert intermittently returns 409 SERVICE_UNAVAILABLE ("The
# operation was aborted.") and the same call succeeds ~10 s later.
#
# Idempotency matters when choosing what to retry:
#   * 409 (transient reason) is safe for ANY method — an aborted write never
#     applied, so re-issuing it cannot duplicate state.
#   * 5xx/429 leave the write status UNKNOWN. Retrying a non-idempotent POST
#     (playlists.insert, playlistItems.insert) could create a duplicate/orphan,
#     so 5xx/429 is retried only for idempotent methods (GET/PUT/DELETE).
# Backoff schedule doubles as the retry count: 3 retries (4 attempts total).
_RETRY_BACKOFFS = (0.5, 1.0, 2.0)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_RETRYABLE_409_REASONS = {"SERVICE_UNAVAILABLE", "ABORTED", "BACKEND_ERROR", "INTERNAL_ERROR"}
_NON_IDEMPOTENT_METHODS = {"POST"}


class YoutubeDataApiClient:
    """Mirrors the YtmusicPublishService client contract using Data API v3.

    ``get_existing_items`` returns playlistItem ids (opaque to the service);
    ``remove_items`` deletes by those ids.
    """

    def __init__(
        self,
        *,
        access_token: str,
        session: Any,
        correlation_id: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = access_token
        self._session = session
        self._correlation_id = correlation_id
        self._sleep = sleep

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
        endpoint = url.rsplit("/", 1)[-1] or url

        status, reason, message = 0, None, None
        for attempt in range(1, len(_RETRY_BACKOFFS) + 2):
            resp = self._session.request(
                method=method, url=url, params=params, data=body, headers=headers,
            )
            status = getattr(resp, "status_code", 0)
            if 200 <= status < 300:
                try:
                    return resp.json()
                except Exception:
                    return {}
            if status == 404 and method == "DELETE" and attempt > 1:
                # A retried DELETE: the earlier attempt likely committed before
                # its transient error surfaced, so the item is already gone.
                return {}

            message, reason = self._error_detail(resp)
            if self._is_retryable(method, status, reason) and attempt <= len(_RETRY_BACKOFFS):
                backoff = _RETRY_BACKOFFS[attempt - 1]
                # Transient YouTube failure (e.g. 409 SERVICE_UNAVAILABLE); the
                # write never applied, so retrying the same call is safe.
                log_event(
                    "WARNING", "ytmusic_api_call_retried",
                    correlation_id=self._correlation_id,
                    status_code=status, reason=reason,
                    phase=f"{method} {endpoint}", attempt=attempt,
                    sleep_seconds=backoff, error_message=message,
                )
                self._sleep(backoff)
                continue
            break

        detail = (
            f"YouTube {status} [{reason}] on {method} {endpoint}: {message}"
            if reason
            else f"YouTube {status} on {method} {endpoint}: {message}"
        )
        # Terminal failure (non-retryable, or retries exhausted). Breadcrumb so
        # the failing call is queryable in CloudWatch even when the caller
        # swallows the error (cover fallback). No token/body is logged.
        log_event(
            "WARNING", "ytmusic_api_call_failed",
            correlation_id=self._correlation_id,
            status_code=status, reason=reason,
            phase=f"{method} {endpoint}", attempt=attempt, error_message=message,
        )
        if status == 401:
            raise YtmusicNotAuthorizedError(detail)
        if status == 404:
            raise YtmusicNotFoundError(detail, status_code=status, reason=reason)
        raise YtmusicApiError(detail, status_code=status, reason=reason)

    @staticmethod
    def _is_retryable(method: str, status: int, reason: str | None) -> bool:
        """Transient failures worth a retry. A 409 with a transient (or absent)
        reason is safe for any method (an aborted write never applied). 5xx/429
        leave the result unknown, so they are retried only for idempotent methods
        — never a non-idempotent POST, which could duplicate state."""
        if status == 409:
            return reason is None or reason.upper() in _RETRYABLE_409_REASONS
        if status in _RETRYABLE_STATUSES:
            return method not in _NON_IDEMPOTENT_METHODS
        return False

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
