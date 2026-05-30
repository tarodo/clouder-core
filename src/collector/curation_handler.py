"""Lambda handler for the user-curation surface (spec-C/D/E).

`_ROUTE_TABLE` is the single source of truth: each `routeKey` maps to a
`(handler, repo_factory)` tuple. spec-D and spec-E will append entries.
Every route is JWT-gated by the API Gateway Lambda Authorizer (spec-A);
`user_id` is read from `event.requestContext.authorizer.lambda.user_id`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from pydantic import ValidationError as PydanticValidationError

from .curation import (
    BadQueryParamError,
    CoverMissingError,
    CoverTooLargeError,
    CurationError,
    InactiveStagingFinalizeError,
    InvalidMatchError,
    InvalidSpotifyRefError,
    InvalidTagColorError,
    InvalidTagIdsError,
    InvalidTagNameError,
    InvalidTagPayloadError,
    NotFoundError,
    PaginatedResult,
    PlaylistNotFoundError,
    SpotifyNotAuthorizedError,
    SpotifyNotFoundError,
    TagNotFoundError,
    TooManyTagsError,
    TrackNotInUserScopeError,
    TracksNotInSourceError,
    ValidationError,
    utc_now,
)
from .curation.categories_repository import (
    CategoriesRepository,
    create_default_categories_repository,
)
from .curation.tags_repository import (
    TagsRepository,
    create_default_tags_repository,
)
from .curation.categories_service import (
    normalize_category_name,
    validate_category_name,
)
from .curation.playlists_repository import (
    PlaylistsRepository,
    create_default_playlists_repository,
)
from .curation.playlists_service import (
    MAX_COVER_BYTES,
    normalize_playlist_name,
    parse_spotify_ref,
    validate_description,
    validate_playlist_name,
)
from .curation.schemas import (
    AddTrackIn,
    AddTracksIn,
    CoverUploadUrlIn,
    CreateCategoryIn,
    CreatePlaylistIn,
    CreateTriageBlockIn,
    ImportSpotifyTracksIn,
    MoveTracksIn,
    PatchPlaylistIn,
    PublishPlaylistIn,
    RenameCategoryIn,
    ReorderCategoriesIn,
    ReorderPlaylistTracksIn,
    ResolveMatchIn,
    TransferTracksIn,
)
from .curation.triage_repository import (
    TriageRepository,
    create_default_triage_repository,
)
from .label_enrichment.auto_dispatch import (
    try_dispatch_for_track,
    try_dispatch_for_triage_block,
)
from .artist_enrichment.auto_dispatch import (
    try_dispatch_artists_for_track,
    try_dispatch_artists_for_triage_block,
)
from .logging_utils import log_event
from .providers.ytmusic.normalize import result_to_ref


# ---------- Constants -------------------------------------------------------

_SORT_VALUES = {"title", "spotify_release_date", "added_at"}
_ORDER_VALUES = {"asc", "desc"}


# ---------- Utility Functions -----------------------------------------------

def _extract_correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers")
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "x-correlation-id":
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return str(uuid.uuid4())


def _json_response(
    status_code: int,
    payload: Mapping[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(payload),
    }


def _error(
    status: int, error_code: str, message: str, correlation_id: str
) -> dict[str, Any]:
    return _json_response(
        status,
        {
            "error_code": error_code,
            "message": message,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _curation_error_response(
    exc: CurationError, correlation_id: str
) -> dict[str, Any]:
    """Map a CurationError to an HTTP envelope, attaching structured payloads
    for error subclasses that carry them (InactiveStagingFinalizeError,
    TracksNotInSourceError)."""

    payload: dict[str, Any] = {
        "error_code": exc.error_code,
        "message": exc.message,
        "correlation_id": correlation_id,
    }
    if isinstance(exc, InactiveStagingFinalizeError):
        payload["inactive_buckets"] = list(exc.inactive_buckets)
    elif isinstance(exc, TracksNotInSourceError):
        payload["not_in_source"] = list(exc.not_in_source)
    elif isinstance(exc, TrackNotInUserScopeError):
        payload["missing_track_ids"] = list(exc.missing_track_ids)
    return _json_response(exc.http_status, payload, correlation_id)


def _user_id_or_none(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authz = rc.get("authorizer")
        if isinstance(authz, Mapping):
            ctx = authz.get("lambda")
            if isinstance(ctx, Mapping):
                uid = ctx.get("user_id")
                if isinstance(uid, str) and uid:
                    return uid
    return None


def _parse_body(event: Mapping[str, Any]) -> Mapping[str, Any]:
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON body: {exc}") from exc
    if isinstance(body, Mapping):
        return body
    raise ValidationError("Invalid body type")


def _parse_pagination(event: Mapping[str, Any]) -> tuple[int, int]:
    qp = event.get("queryStringParameters") or {}
    raw_limit = qp.get("limit", "50")
    raw_offset = qp.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ValidationError("offset must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    return limit, offset


def _category_response(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "position": row.position,
        "track_count": row.track_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _playlist_response(row, storage=None) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "description": row.description,
        "is_public": row.is_public,
        "cover_s3_key": row.cover_s3_key,
        "cover_url": None,
        "cover_uploaded_at": row.cover_uploaded_at,
        "spotify_playlist_id": row.spotify_playlist_id,
        "last_published_at": row.last_published_at,
        "needs_republish": row.needs_republish,
        "track_count": row.track_count,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if row.cover_s3_key and storage is not None:
        payload["cover_url"] = storage.presigned_cover_get_url(
            s3_key=row.cover_s3_key,
        )
    return payload


def _build_storage_if_needed(rows):
    """Return an S3Storage only if any of the given rows carries a cover."""
    if any(getattr(r, "cover_s3_key", None) for r in rows):
        return _build_s3_storage()
    return None


def _playlist_track_response(row) -> dict[str, Any]:
    return {
        "track_id": row.track_id,
        "position": row.position,
        "added_at": row.added_at,
        "title": row.title,
        "spotify_id": row.spotify_id,
        "isrc": row.isrc,
        "length_ms": row.length_ms,
        "origin": row.origin,
        "mix_name": getattr(row, "mix_name", None),
        "bpm": getattr(row, "bpm", None),
        "spotify_release_date": getattr(row, "spotify_release_date", None),
        "is_ai_suspected": bool(getattr(row, "is_ai_suspected", False)),
        "artists": list(getattr(row, "artists", ())),
        "label": getattr(row, "label", None),
        "tags": [
            {"id": t.tag_id, "name": t.name, "color": t.color}
            for t in getattr(row, "tags", ())
        ],
        "ytmusic": getattr(row, "ytmusic", None),
    }


def _project_candidate(c: dict) -> dict[str, Any]:
    ref = c.get("ref") or {}
    vt = result_to_ref(ref)
    vid = vt.vendor_track_id if vt else str(ref.get("videoId") or "")
    return {
        "vendor_track_id": vid,
        "title": vt.title if vt else str(ref.get("title") or ""),
        "artists": list(vt.artist_names) if vt else [],
        "album": vt.album_name if vt else None,
        "duration_ms": vt.duration_ms if vt else None,
        "url": f"https://music.youtube.com/watch?v={vid}",
        "score": c.get("score"),
    }


def _vendor_from_query(event) -> str:
    qp = event.get("queryStringParameters") or {}
    return (qp.get("vendor") or "ytmusic").strip() or "ytmusic"


def _scope_check(repo, user_id, pid, track_id):
    if repo.get(user_id=user_id, playlist_id=pid) is None:
        raise PlaylistNotFoundError("Playlist not found")
    visible = repo.validate_tracks_in_scope(user_id=user_id, track_ids=[track_id])
    if track_id not in visible:
        raise TrackNotInUserScopeError("Track not accessible to the user", [track_id])


def _handle_match_candidates(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    pid, track_id = pp.get("id"), pp.get("track_id")
    if not pid or not track_id:
        raise ValidationError("id and track_id are required in path")
    vendor = _vendor_from_query(event)
    _scope_check(repo, user_id, pid, track_id)
    review = repo.get_open_review(track_id=track_id, vendor=vendor)
    if review is None:
        raise NotFoundError("no_open_review", "No open review for this track")
    return _json_response(
        200,
        {"vendor": vendor,
         "candidates": [_project_candidate(c) for c in review.candidates]},
        correlation_id,
    )


def _ytmusic_status_dict(status) -> dict[str, Any] | None:
    if status is None:
        return None
    return {"status": status.status, "video_id": status.video_id,
            "url": status.url, "confidence": status.confidence}


def _handle_resolve_match(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    pid, track_id = pp.get("id"), pp.get("track_id")
    if not pid or not track_id:
        raise ValidationError("id and track_id are required in path")
    body = ResolveMatchIn.model_validate(_parse_body(event))
    _scope_check(repo, user_id, pid, track_id)

    if body.action == "accept":
        review = repo.get_open_review(track_id=track_id, vendor=body.vendor)
        payload: dict[str, Any] = {
            "videoId": body.vendor_track_id,
            "url": f"https://music.youtube.com/watch?v={body.vendor_track_id}",
            "source": "manual_url",
        }
        if review is not None:
            for c in review.candidates:
                ref = c.get("ref") or {}
                if str(ref.get("videoId") or "") == body.vendor_track_id:
                    payload = ref
                    break
        repo.resolve_review_accept(
            clouder_track_id=track_id, vendor=body.vendor,
            vendor_track_id=body.vendor_track_id, payload=payload, now=utc_now(),
        )
    else:
        repo.resolve_review_reject(
            clouder_track_id=track_id, vendor=body.vendor, now=utc_now(),
        )

    status = repo.fetch_ytmusic_status([track_id]).get(track_id)
    log_event(
        "INFO", "match_review_resolved",
        correlation_id=correlation_id, user_id=user_id,
        track_id=track_id, vendor=body.vendor, action=body.action,
    )
    return _json_response(200, {"ytmusic": _ytmusic_status_dict(status)}, correlation_id)


def _enqueue_ytmusic(repo, added_track_ids, correlation_id) -> None:
    """Best-effort: enqueue YT Music match jobs for newly added tracks.

    Never raises — a failure here must not fail the track-add request.
    """
    if not added_track_ids:
        return
    try:
        import boto3

        from collector.settings import get_api_settings
        from collector.vendor_match.enqueue import (
            YTMUSIC_VENDOR,
            enqueue_vendor_matches,
        )

        queue_url = get_api_settings().vendor_match_queue_url
        if not queue_url:
            return
        inputs = repo.fetch_unmatched_match_inputs(
            track_ids=list(added_track_ids), vendor=YTMUSIC_VENDOR,
        )
        enqueue_vendor_matches(
            track_inputs=inputs,
            vendor=YTMUSIC_VENDOR,
            queue_url=queue_url,
            sqs=boto3.client("sqs"),
            correlation_id=correlation_id,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            "ERROR", "vendor_match_enqueue_unexpected",
            correlation_id=correlation_id, error_message=str(exc),
        )


def _paginated_response(
    result, mapper, correlation_id: str
) -> dict[str, Any]:
    return _json_response(
        200,
        {
            "items": [mapper(r) for r in result.items],
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


# ---------- Routing ---------------------------------------------------------

def lambda_handler(
    event: Mapping[str, Any], context: Any
) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)

    user_id = _user_id_or_none(event)
    if user_id is None:
        return _error(401, "unauthorized", "Missing authorizer context", correlation_id)

    rc = event.get("requestContext") or {}
    route_key = rc.get("routeKey") if isinstance(rc, Mapping) else None
    if not isinstance(route_key, str):
        return _error(404, "not_found", "Unknown route", correlation_id)

    entry = _ROUTE_TABLE.get(route_key)
    if entry is None:
        return _error(404, "not_found", "Unknown route", correlation_id)

    handler, factory = entry
    repo = factory()
    if repo is None:
        return _error(503, "db_not_configured", "Database not configured", correlation_id)

    try:
        return handler(event, repo, user_id, correlation_id)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "body"
        return _error(
            422,
            "validation_error",
            f"{loc}: {first['msg']}",
            correlation_id,
        )
    except CurationError as exc:
        return _curation_error_response(exc, correlation_id)
    except Exception as exc:  # noqa: BLE001
        # `error` is not in ALLOWED_LOG_FIELDS — structlog drops unknown
        # fields silently. Use whitelisted error_message + error_type.
        log_event(
            "ERROR",
            "curation_handler_unhandled",
            correlation_id=correlation_id,
            error_message=str(exc),
            error_type=type(exc).__name__,
        )
        return _error(500, "internal_error", "Internal error", correlation_id)


# ---------- Route handlers (Tasks 14–22 fill in) ----------------------------

# Each takes (event, repo, user_id, correlation_id) and returns a Lambda response dict.


def _handle_create_category(
    event, repo: CategoriesRepository, user_id: str, correlation_id: str
):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    body = CreateCategoryIn.model_validate(_parse_body(event))
    validate_category_name(body.name)
    normalized = normalize_category_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    category_id = str(uuid.uuid4())
    now = utc_now()
    row = repo.create(
        user_id=user_id,
        style_id=style_id,
        category_id=category_id,
        name=body.name.strip(),
        normalized_name=normalized,
        now=now,
        correlation_id=correlation_id,
    )
    log_event(
        "INFO",
        "category_created",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=row.id,
        style_id=row.style_id,
    )
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(201, payload, correlation_id)


def _handle_list_by_style(event, repo, user_id, correlation_id):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    limit, offset = _parse_pagination(event)
    result = repo.list_by_style(
        user_id=user_id, style_id=style_id, limit=limit, offset=offset,
    )
    return _paginated_response(result, _category_response, correlation_id)


def _handle_list_all(event, repo, user_id, correlation_id):
    limit, offset = _parse_pagination(event)
    result = repo.list_all(user_id=user_id, limit=limit, offset=offset)
    return _paginated_response(result, _category_response, correlation_id)


def _handle_get_detail(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    row = repo.get(user_id=user_id, category_id=cid)
    if row is None:
        raise NotFoundError("category_not_found", "Category not found")
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_rename(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    body = RenameCategoryIn.model_validate(_parse_body(event))
    validate_category_name(body.name)
    normalized = normalize_category_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    row = repo.rename(
        user_id=user_id,
        category_id=cid,
        name=body.name.strip(),
        normalized_name=normalized,
        now=utc_now(),
    )
    log_event(
        "INFO",
        "category_renamed",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=row.id,
    )
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_soft_delete(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    tags_repo = create_default_tags_repository()
    if tags_repo is None:
        return _error(
            503, "db_not_configured", "Database not configured", correlation_id,
        )
    deleted = repo.soft_delete(
        user_id=user_id,
        category_id=cid,
        now=utc_now(),
        correlation_id=correlation_id,
        tags_repo=tags_repo,
    )
    if not deleted:
        raise NotFoundError("category_not_found", "Category not found")
    log_event(
        "INFO",
        "category_soft_deleted",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


def _handle_reorder(event, repo, user_id, correlation_id):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    body = ReorderCategoriesIn.model_validate(_parse_body(event))
    rows = repo.reorder(
        user_id=user_id,
        style_id=style_id,
        ordered_ids=body.category_ids,
        now=utc_now(),
    )
    log_event(
        "INFO",
        "category_order_updated",
        correlation_id=correlation_id,
        user_id=user_id,
        style_id=style_id,
        size=len(rows),
    )
    return _json_response(
        200,
        {
            "items": [_category_response(r) for r in rows],
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _track_in_category_response(item) -> dict[str, Any]:
    track = dict(item.track)
    track["added_at"] = item.added_at
    track["source_triage_block_id"] = item.source_triage_block_id
    track["tags"] = [
        {"id": t.tag_id, "name": t.name, "color": t.color}
        for t in getattr(item, "tags", ())
    ]
    track["used_in_playlist"] = bool(track.get("used_in_playlist", False))
    return track


def _handle_list_tracks(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")

    sort = (qp.get("sort") or "added_at").lower()
    if sort not in _SORT_VALUES:
        raise BadQueryParamError(
            f"sort must be one of {sorted(_SORT_VALUES)}"
        )
    order = (qp.get("order") or "desc").lower()
    if order not in _ORDER_VALUES:
        raise BadQueryParamError("order must be 'asc' or 'desc'")

    tags_raw = qp.get("tags")
    tag_ids = [t for t in (tags_raw.split(",") if tags_raw else []) if t]
    tag_match = (qp.get("match") or "all").lower()
    if tag_match not in ("all", "any"):
        raise InvalidMatchError("match must be 'all' or 'any'")

    tags_repo = create_default_tags_repository()
    if tags_repo is None:
        return _error(
            503, "db_not_configured", "Database not configured", correlation_id,
        )

    fresh_raw = (qp.get("fresh") or "").strip()
    fresh = fresh_raw == "1"

    result = repo.list_tracks(
        user_id=user_id, category_id=cid,
        limit=limit, offset=offset, search=search,
        sort=sort, order=order,
        tag_ids=tag_ids or None, tag_match=tag_match, tags_repo=tags_repo,
        fresh=fresh,
    )
    return _paginated_response(
        result, _track_in_category_response, correlation_id
    )


def _handle_add_track(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    body = AddTrackIn.model_validate(_parse_body(event))
    result, was_new = repo.add_track(
        user_id=user_id, category_id=cid, track_id=body.track_id,
        source_triage_block_id=None, now=utc_now(),
    )
    log_event(
        "INFO",
        "category_track_added",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
        track_id=body.track_id,
        result="added" if was_new else "already_present",
    )
    if was_new:
        try_dispatch_for_track(track_id=body.track_id, user_id=user_id)
        try_dispatch_artists_for_track(track_id=body.track_id, user_id=user_id)
    payload = {
        "result": "added" if was_new else "already_present",
        "added_at": result["added_at"],
        "source_triage_block_id": result["source_triage_block_id"],
        "correlation_id": correlation_id,
    }
    return _json_response(201 if was_new else 200, payload, correlation_id)


def _handle_remove_track(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    cid = pp.get("id")
    tid = pp.get("track_id")
    if not cid or not tid:
        raise ValidationError("id and track_id are required in path")
    tags_repo = create_default_tags_repository()
    if tags_repo is None:
        return _error(
            503, "db_not_configured", "Database not configured", correlation_id,
        )
    deleted = repo.remove_track(
        user_id=user_id, category_id=cid, track_id=tid, tags_repo=tags_repo,
    )
    if not deleted:
        raise NotFoundError("track_not_in_category", "Track not in category")
    log_event(
        "INFO",
        "category_track_removed",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
        track_id=tid,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


# ---------- Playlist CRUD handlers ------------------------------------------


def _handle_create_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    body = CreatePlaylistIn.model_validate(_parse_body(event))
    validate_playlist_name(body.name)
    validate_description(body.description)
    normalized = normalize_playlist_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    playlist_id = str(uuid.uuid4())
    row = repo.create(
        user_id=user_id,
        playlist_id=playlist_id,
        name=body.name.strip(),
        normalized_name=normalized,
        description=body.description,
        is_public=body.is_public,
        now=utc_now(),
    )
    log_event(
        "INFO", "playlist_created",
        correlation_id=correlation_id, user_id=user_id, playlist_id=row.id,
    )
    payload = _playlist_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(201, payload, correlation_id)


def _handle_list_playlists(event, repo: PlaylistsRepository, user_id, correlation_id):
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    status = qp.get("status")
    if status is not None and status not in ("active", "completed"):
        raise ValidationError("status must be 'active' or 'completed'")
    rows, total = repo.list_all(
        user_id=user_id, limit=limit, offset=offset, status=status,
    )
    storage = _build_storage_if_needed(rows)
    return _json_response(
        200,
        {
            "items": [_playlist_response(r, storage) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_get_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    row = repo.get(user_id=user_id, playlist_id=pid)
    if row is None:
        raise PlaylistNotFoundError()
    storage = _build_s3_storage() if row.cover_s3_key else None
    payload = _playlist_response(row, storage)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_patch_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = PatchPlaylistIn.model_validate(_parse_body(event))
    name = body.name.strip() if body.name is not None else None
    normalized = normalize_playlist_name(body.name) if body.name is not None else None
    if body.name is not None:
        validate_playlist_name(body.name)
    if body.description is not None:
        validate_description(body.description)
    row = repo.patch(
        user_id=user_id, playlist_id=pid,
        name=name, normalized_name=normalized,
        description=body.description, is_public=body.is_public,
        status=body.status,
        now=utc_now(),
    )
    log_event(
        "INFO", "playlist_patched",
        correlation_id=correlation_id, user_id=user_id, playlist_id=pid,
    )
    storage = _build_s3_storage() if row.cover_s3_key else None
    payload = _playlist_response(row, storage)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_delete_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    ok = repo.soft_delete(user_id=user_id, playlist_id=pid, now=utc_now())
    if not ok:
        raise PlaylistNotFoundError()
    log_event(
        "INFO", "playlist_deleted",
        correlation_id=correlation_id, user_id=user_id, playlist_id=pid,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


def _handle_list_playlist_tracks(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    tags_repo = create_default_tags_repository()
    if tags_repo is None:
        return _error(503, "db_not_configured", "Database not configured", correlation_id)
    rows, total = repo.list_tracks(
        user_id=user_id, playlist_id=pid, limit=limit, offset=offset,
        tags_repo=tags_repo,
    )
    return _json_response(
        200,
        {
            "items": [_playlist_track_response(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_add_playlist_tracks(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = AddTracksIn.model_validate(_parse_body(event))
    visible = repo.validate_tracks_in_scope(
        user_id=user_id, track_ids=body.track_ids,
    )
    missing = [t for t in body.track_ids if t not in visible]
    if missing:
        raise TrackNotInUserScopeError(
            "Some tracks are not accessible to the user", missing,
        )
    result = repo.append_tracks(
        user_id=user_id, playlist_id=pid,
        track_ids=body.track_ids, now=utc_now(),
    )
    log_event(
        "INFO", "playlist_track_added",
        correlation_id=correlation_id, user_id=user_id,
        playlist_id=pid, n=len(result.added_track_ids),
    )
    _enqueue_ytmusic(repo, result.added_track_ids, correlation_id)
    return _json_response(
        201,
        {
            "added": result.added_track_ids,
            "skipped_duplicates": result.skipped_duplicates,
            "position_after": result.position_after,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_remove_playlist_track(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    pid = pp.get("id")
    track_id = pp.get("track_id")
    if not pid or not track_id:
        raise ValidationError("id and track_id are required in path")
    ok = repo.remove_track(
        user_id=user_id, playlist_id=pid, track_id=track_id, now=utc_now(),
    )
    if not ok:
        raise PlaylistNotFoundError("Playlist or track not found")
    log_event(
        "INFO", "playlist_track_removed",
        correlation_id=correlation_id, user_id=user_id,
        playlist_id=pid, track_id=track_id,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


def _handle_reorder_playlist_tracks(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = ReorderPlaylistTracksIn.model_validate(_parse_body(event))
    repo.reorder_tracks(
        user_id=user_id, playlist_id=pid,
        ordered_track_ids=body.track_ids, now=utc_now(),
    )
    log_event(
        "INFO", "playlist_track_reordered",
        correlation_id=correlation_id, user_id=user_id,
        playlist_id=pid, size=len(body.track_ids),
    )
    return _json_response(200, {"correlation_id": correlation_id}, correlation_id)


# ---------- Playlist cover handlers -----------------------------------------


def _handle_cover_upload_url(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = CoverUploadUrlIn.model_validate(_parse_body(event))
    # Ownership check: 404 if not user's playlist.
    if repo.get(user_id=user_id, playlist_id=pid) is None:
        raise PlaylistNotFoundError()
    storage = _build_s3_storage()
    epoch_ms = int(utc_now().timestamp() * 1000)
    s3_key = storage.cover_key(
        user_id=user_id, playlist_id=pid, epoch_ms=epoch_ms,
    )
    url = storage.presigned_cover_put_url(
        s3_key=s3_key, content_type=body.content_type, expires_in=300,
    )
    log_event(
        "INFO", "playlist_cover_upload_url_issued",
        correlation_id=correlation_id, user_id=user_id, playlist_id=pid,
    )
    return _json_response(
        200,
        {"upload_url": url, "s3_key": s3_key, "expires_in": 300,
         "correlation_id": correlation_id},
        correlation_id,
    )


def _handle_cover_confirm(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = _parse_body(event)
    s3_key = body.get("s3_key") if isinstance(body, dict) else None
    if not isinstance(s3_key, str) or not s3_key.startswith(f"covers/{user_id}/"):
        raise ValidationError("s3_key is required and must belong to the caller")
    if repo.get(user_id=user_id, playlist_id=pid) is None:
        raise PlaylistNotFoundError()
    storage = _build_s3_storage()
    info = storage.head_cover(s3_key)
    if info is None:
        raise CoverMissingError(f"No object at {s3_key}")
    if info["size"] > MAX_COVER_BYTES:
        raise CoverTooLargeError(
            f"Cover exceeds {MAX_COVER_BYTES} bytes ({info['size']})"
        )
    ok = repo.set_cover(
        user_id=user_id, playlist_id=pid, s3_key=s3_key, now=utc_now(),
    )
    if not ok:
        raise PlaylistNotFoundError()
    log_event(
        "INFO", "playlist_cover_confirmed",
        correlation_id=correlation_id, user_id=user_id, playlist_id=pid,
    )
    row = repo.get(user_id=user_id, playlist_id=pid)
    # Storage already built above for HEAD; reuse for presigned GET URL.
    payload = _playlist_response(row, storage)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_cover_delete(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    ok = repo.clear_cover(user_id=user_id, playlist_id=pid, now=utc_now())
    if not ok:
        raise PlaylistNotFoundError()
    log_event(
        "INFO", "playlist_cover_deleted",
        correlation_id=correlation_id, user_id=user_id, playlist_id=pid,
    )
    row = repo.get(user_id=user_id, playlist_id=pid)
    # Cover was just cleared; cover_url will be None regardless of storage.
    payload = _playlist_response(row, None)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


# ---------- Playlist import + publish handlers ------------------------------


def _handle_import_spotify(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = ImportSpotifyTracksIn.model_validate(_parse_body(event))
    if repo.get(user_id=user_id, playlist_id=pid) is None:
        raise PlaylistNotFoundError()

    # Parse refs; collect invalid for response.
    spotify_ids: list[str] = []
    skipped: list[dict] = []
    for ref in body.spotify_refs:
        try:
            sid = parse_spotify_ref(ref)
        except InvalidSpotifyRefError:
            skipped.append({"ref": ref, "reason": "invalid_ref"})
            continue
        spotify_ids.append(sid)

    log_event(
        "INFO", "playlist_spotify_import_requested",
        correlation_id=correlation_id, user_id=user_id, playlist_id=pid,
        refs_count=len(body.spotify_refs),
    )

    sp_client = _build_spotify_user_client(user_id, correlation_id)

    track_ids: list[str] = []
    added_details: list[dict] = []
    for sid in spotify_ids:
        try:
            payload = sp_client.get_track(sid)
        except SpotifyNotFoundError as exc:
            skipped.append({"ref": sid, "reason": "not_found"})
            log_event(
                "WARNING", "playlist_spotify_import_failed",
                correlation_id=correlation_id, user_id=user_id,
                spotify_id=sid, reason=str(exc),
            )
            continue
        track_id = repo.upsert_imported_track(
            user_id=user_id,
            spotify_id=payload.id,
            title=payload.name,
            isrc=payload.isrc,
            length_ms=payload.duration_ms,
            now=utc_now(),
        )
        track_ids.append(track_id)
        added_details.append({
            "track_id": track_id,
            "spotify_id": payload.id,
            "title": payload.name,
        })
        log_event(
            "INFO", "playlist_spotify_track_imported",
            correlation_id=correlation_id, user_id=user_id,
            spotify_id=payload.id,
        )

    if track_ids:
        result = repo.append_tracks(
            user_id=user_id, playlist_id=pid,
            track_ids=track_ids, now=utc_now(),
        )
        position_after = result.position_after
        # Tracks already in this playlist surface as skipped duplicates.
        for dup in result.skipped_duplicates:
            skipped.append({"ref": dup, "reason": "already_in_playlist"})
        _enqueue_ytmusic(repo, result.added_track_ids, correlation_id)
    else:
        position_after = 0

    return _json_response(
        201,
        {
            "added": added_details,
            "skipped": skipped,
            "position_after": position_after,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_publish(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = PublishPlaylistIn.model_validate(_parse_body(event))

    sp_client = _build_spotify_user_client(user_id, correlation_id)
    storage = _build_s3_storage()

    from .curation.playlists_publish_service import (
        PlaylistsPublishService,
        UserSpotifyIdReader,
    )

    # Build user-id reader on top of the same Data API client the repo uses.
    user_repo = UserSpotifyIdReader(repo.data_api)

    svc = PlaylistsPublishService(
        repo=repo, spotify_client=sp_client,
        user_repo=user_repo, storage=storage,
    )
    result = svc.publish(
        user_id=user_id, playlist_id=pid,
        confirm_overwrite=body.confirm_overwrite,
    )
    return _json_response(
        200,
        {
            "spotify_playlist_id": result.spotify_playlist_id,
            "spotify_url": result.spotify_url,
            "skipped_tracks": result.skipped,
            "cover_failed": result.cover_failed,
            "published_at": result.published_at,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


# ---------- spec-D triage handlers ------------------------------------------


def _serialize_triage_block(row, correlation_id: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "old_offset_weeks": row.old_offset_weeks,
        "include_disliked_labels": row.include_disliked_labels,
        "include_disliked_artists": row.include_disliked_artists,
        "compilations_to_not": row.compilations_to_not,
        "include_favorites": row.include_favorites,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "buckets": [
            {
                "id": b.id,
                "bucket_type": b.bucket_type,
                "category_id": b.category_id,
                "category_name": b.category_name,
                "inactive": b.inactive,
                "track_count": b.track_count,
            }
            for b in row.buckets
        ],
        "correlation_id": correlation_id,
    }


def _create_triage_block(
    event, triage_repo: TriageRepository, user_id: str, correlation_id: str
):
    schema = CreateTriageBlockIn.model_validate(_parse_body(event))
    out = triage_repo.create_block(
        user_id=user_id,
        style_id=schema.style_id,
        name=schema.name,
        date_from=schema.date_from,
        date_to=schema.date_to,
        old_offset_weeks=schema.old_offset_weeks,
        include_disliked_labels=schema.include_disliked_labels,
        include_disliked_artists=schema.include_disliked_artists,
        compilations_to_not=schema.compilations_to_not,
        include_favorites=schema.include_favorites,
    )
    log_event(
        "INFO",
        "triage_block_created",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=out.id,
        style_id=out.style_id,
        date_from=out.date_from,
        date_to=out.date_to,
    )
    return _json_response(
        201, _serialize_triage_block(out, correlation_id), correlation_id
    )


def _serialize_block_summary(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "track_count": row.track_count,
    }


def _serialize_bucket_track(row) -> dict[str, Any]:
    return {
        "track_id": row.track_id,
        "title": row.title,
        "mix_name": row.mix_name,
        "isrc": row.isrc,
        "bpm": row.bpm,
        "length_ms": row.length_ms,
        "publish_date": row.publish_date,
        "spotify_release_date": row.spotify_release_date,
        "spotify_id": row.spotify_id,
        "release_type": row.release_type,
        "is_ai_suspected": row.is_ai_suspected,
        "artists": row.artists,
        "label_name": row.label_name,
        "label_id": row.label_id,
        "added_at": row.added_at,
    }


def _parse_status_query(event: Mapping[str, Any]) -> str | None:
    qp = event.get("queryStringParameters") or {}
    status = qp.get("status")
    if status is None:
        return None
    if status not in ("IN_PROGRESS", "FINALIZED"):
        raise ValidationError("status must be IN_PROGRESS or FINALIZED")
    return status


def _list_triage_blocks_by_style(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    limit, offset = _parse_pagination(event)
    status = _parse_status_query(event)

    items, total = repo.list_blocks_by_style(
        user_id=user_id,
        style_id=style_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    log_event(
        "INFO",
        "triage_block_listed",
        correlation_id=correlation_id,
        user_id=user_id,
        style_id=style_id,
        count=len(items),
        total=total,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _list_triage_blocks_all(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    limit, offset = _parse_pagination(event)
    status = _parse_status_query(event)

    items, total = repo.list_blocks_all(
        user_id=user_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _get_triage_block(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")
    out = repo.get_block(user_id=user_id, block_id=block_id)
    if out is None:
        raise NotFoundError(
            "triage_block_not_found",
            f"triage block not found: {block_id}",
        )
    return _json_response(
        200, _serialize_triage_block(out, correlation_id), correlation_id
    )


def _list_bucket_tracks(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    pp = event.get("pathParameters") or {}
    block_id = pp.get("id")
    bucket_id = pp.get("bucket_id")
    if not block_id or not bucket_id:
        raise ValidationError("id and bucket_id are required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")

    items, total = repo.list_bucket_tracks(
        user_id=user_id,
        block_id=block_id,
        bucket_id=bucket_id,
        limit=limit,
        offset=offset,
        search=search,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_bucket_track(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _move_tracks(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")
    schema = MoveTracksIn.model_validate(_parse_body(event))

    out = repo.move_tracks(
        user_id=user_id,
        block_id=block_id,
        from_bucket_id=schema.from_bucket_id,
        to_bucket_id=schema.to_bucket_id,
        track_ids=schema.track_ids,
    )
    log_event(
        "INFO",
        "triage_tracks_moved",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
        from_bucket_id=schema.from_bucket_id,
        to_bucket_id=schema.to_bucket_id,
        moved=out.moved,
    )
    return _json_response(
        200,
        {"moved": out.moved, "correlation_id": correlation_id},
        correlation_id,
    )


def _transfer_tracks(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    src_block_id = (event.get("pathParameters") or {}).get("src_id")
    if not src_block_id:
        raise ValidationError("src_id is required in path")
    schema = TransferTracksIn.model_validate(_parse_body(event))

    out = repo.transfer_tracks(
        user_id=user_id,
        src_block_id=src_block_id,
        target_bucket_id=schema.target_bucket_id,
        track_ids=schema.track_ids,
    )
    log_event(
        "INFO",
        "triage_tracks_transferred",
        correlation_id=correlation_id,
        user_id=user_id,
        src_block_id=src_block_id,
        target_bucket_id=schema.target_bucket_id,
        transferred=out.transferred,
    )
    return _json_response(
        200,
        {"transferred": out.transferred, "correlation_id": correlation_id},
        correlation_id,
    )


def _finalize_triage_block(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")

    cat_repo = create_default_categories_repository()
    if cat_repo is None:
        # Triage factory already gated on db config, so this is a defensive
        # mismatch guard — both factories read the same Aurora env vars.
        return _error(
            503, "db_not_configured", "Database not configured", correlation_id
        )

    out = repo.finalize_block(
        user_id=user_id,
        block_id=block_id,
        categories_repository=cat_repo,
    )
    log_event(
        "INFO",
        "triage_block_finalized",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
        promoted_count=sum(out.promoted.values()),
    )
    try_dispatch_for_triage_block(block_id=block_id, user_id=user_id)
    try_dispatch_artists_for_triage_block(block_id=block_id, user_id=user_id)
    return _json_response(
        200,
        {
            "block": _serialize_triage_block(out.block, correlation_id),
            "promoted": out.promoted,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _soft_delete_triage_block(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")
    deleted = repo.soft_delete_block(
        user_id=user_id, block_id=block_id
    )
    if not deleted:
        raise NotFoundError(
            "triage_block_not_found",
            f"triage block not found: {block_id}",
        )
    log_event(
        "INFO",
        "triage_block_soft_deleted",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


# ---------- Track-tags handlers (spec 2026-05-11) ---------------------------

import re as _re

_HEX_COLOR_RE = _re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAX_TAG_NAME = 64
_MAX_TAGS_PER_TRACK = 50


def _normalize_tag_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _tag_dict(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "color": row.color,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _track_tag_dict(row) -> dict[str, Any]:
    return {"id": row.tag_id, "name": row.name, "color": row.color}


def _no_content(correlation_id: str) -> dict[str, Any]:
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


def _handle_create_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    body = _parse_body(event)
    name_raw = body.get("name")
    color = body.get("color")
    if not isinstance(name_raw, str):
        raise InvalidTagNameError("name is required")
    name = name_raw.strip()
    if not name or len(name) > _MAX_TAG_NAME:
        raise InvalidTagNameError("name must be 1..64 chars")
    if color is not None:
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            raise InvalidTagColorError("color must be #RRGGBB hex or null")
    row = repo.create_tag(
        user_id=user_id,
        tag_id=str(uuid.uuid4()),
        name=name,
        normalized_name=_normalize_tag_name(name),
        color=color,
        now=utc_now(),
    )
    return _json_response(201, _tag_dict(row), correlation_id)


def _handle_list_tags(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")
    page = repo.list_tags(
        user_id=user_id, limit=limit, offset=offset, search=search,
    )
    return _json_response(
        200,
        {
            "items": [_tag_dict(r) for r in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        },
        correlation_id,
    )


def _handle_rename_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    tag_id = (event.get("pathParameters") or {}).get("tag_id")
    if not tag_id:
        raise ValidationError("tag_id is required in path")
    body = _parse_body(event)
    has_name = "name" in body
    has_color = "color" in body
    name = body.get("name") if has_name else None
    color = body.get("color") if has_color else None
    normalized: str | None = None
    if has_name:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > _MAX_TAG_NAME:
            raise InvalidTagNameError("name must be 1..64 chars")
        name = name.strip()
        normalized = _normalize_tag_name(name)
    if has_color and color is not None:
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            raise InvalidTagColorError("color must be #RRGGBB hex or null")
    if not has_name and not has_color:
        raise InvalidTagPayloadError(
            "at least one of name|color required"
        )
    row = repo.rename_tag(
        user_id=user_id, tag_id=tag_id,
        name=name, normalized_name=normalized,
        color=color, clear_color=has_color,
        now=utc_now(),
    )
    return _json_response(200, _tag_dict(row), correlation_id)


def _handle_delete_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    tag_id = (event.get("pathParameters") or {}).get("tag_id")
    if not tag_id:
        raise ValidationError("tag_id is required in path")
    ok = repo.delete_tag(user_id=user_id, tag_id=tag_id)
    if not ok:
        raise TagNotFoundError()
    return _no_content(correlation_id)


def _handle_list_track_tags(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    grouped = repo.list_tags_for_tracks(user_id=user_id, track_ids=[track_id])
    items = grouped.get(track_id, [])
    return _json_response(
        200, {"tags": [_track_tag_dict(r) for r in items]}, correlation_id,
    )


def _handle_set_track_tags(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    body = _parse_body(event)
    tag_ids = body.get("tag_ids")
    if not isinstance(tag_ids, list):
        raise InvalidTagIdsError("tag_ids must be an array")
    if len(tag_ids) > _MAX_TAGS_PER_TRACK:
        raise TooManyTagsError(
            f"Maximum {_MAX_TAGS_PER_TRACK} tags per track"
        )
    if any(not isinstance(t, str) or not t for t in tag_ids):
        raise InvalidTagIdsError("tag_ids must be non-empty strings")
    if len(set(tag_ids)) != len(tag_ids):
        raise InvalidTagIdsError("Duplicate tag ids")
    out = repo.set_track_tags(
        user_id=user_id, track_id=track_id, tag_ids=tag_ids, now=utc_now(),
    )
    return _json_response(
        200, {"tags": [_tag_dict(r) for r in out]}, correlation_id,
    )


def _handle_add_track_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    body = _parse_body(event)
    tag_id = body.get("tag_id")
    if not isinstance(tag_id, str) or not tag_id:
        raise InvalidTagIdsError("tag_id required")
    out = repo.add_track_tag(
        user_id=user_id, track_id=track_id, tag_id=tag_id, now=utc_now(),
    )
    return _json_response(
        201, {"tags": [_tag_dict(r) for r in out]}, correlation_id,
    )


def _handle_remove_track_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    pp = event.get("pathParameters") or {}
    track_id = pp.get("track_id")
    tag_id = pp.get("tag_id")
    if not track_id or not tag_id:
        raise ValidationError("track_id and tag_id are required in path")
    repo.remove_track_tag(user_id=user_id, track_id=track_id, tag_id=tag_id)
    return _no_content(correlation_id)


# Single source of truth for routing: each route maps to a
# `(handler, repo_factory)` tuple. Adding a new route requires picking the
# right factory explicitly — there is no silent fallback. spec-C routes use
# `create_default_categories_repository`; spec-D triage routes use
# `create_default_triage_repository`.
def _categories_factory() -> Any:
    return create_default_categories_repository()


def _triage_factory() -> Any:
    return create_default_triage_repository()


def _tags_factory() -> Any:
    return create_default_tags_repository()


def _playlists_factory() -> Any:
    return create_default_playlists_repository()


def _build_s3_storage():
    """Build an S3Storage for cover ops in the curation Lambda."""
    import boto3
    from collector.settings import get_api_settings
    from collector.storage import S3Storage

    settings = get_api_settings()
    return S3Storage(
        s3_client=boto3.client("s3"),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.raw_prefix,
    )


def _build_spotify_user_client(user_id: str, correlation_id: str):
    """Build a SpotifyUserClient with a freshly-resolved user access token.

    Lazy imports to keep cold-start lean. Token refresh + KMS decrypt go
    through SpotifyTokenResolver. Raises SpotifyNotAuthorizedError if the
    user has no token row or refresh fails — the handler's error envelope
    surfaces it as 412.
    """
    import boto3
    import requests as _requests
    from collector.auth.auth_settings import (
        get_auth_settings,
        resolve_oauth_client_credentials,
    )
    from collector.auth.kms_envelope import KmsEnvelope
    from collector.auth.spotify_oauth import SpotifyOAuthClient
    from collector.curation.spotify_token_resolver import SpotifyTokenResolver
    from collector.curation.spotify_user_client import SpotifyUserClient
    from collector.data_api import create_default_data_api_client
    from collector.settings import get_data_api_settings

    db = get_data_api_settings()
    auth = get_auth_settings()
    cid, csec = resolve_oauth_client_credentials()
    data_api = create_default_data_api_client(
        resource_arn=str(db.aurora_cluster_arn),
        secret_arn=str(db.aurora_secret_arn),
        database=db.aurora_database,
    )
    envelope = KmsEnvelope(
        kms_client=boto3.client("kms"),
        key_arn=auth.kms_user_tokens_key_arn,
    )
    oauth = SpotifyOAuthClient(
        client_id=cid, client_secret=csec,
        redirect_uri=auth.spotify_oauth_redirect_uri,
    )
    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    token = resolver.resolve(user_id=user_id)
    return SpotifyUserClient(
        access_token=token.access_token,
        session=_requests.Session(),
    )


_ROUTE_TABLE: dict[str, tuple[Callable[..., dict[str, Any]], Callable[[], Any]]] = {
    "POST /styles/{style_id}/categories": (_handle_create_category, _categories_factory),
    "GET /styles/{style_id}/categories": (_handle_list_by_style, _categories_factory),
    "GET /categories": (_handle_list_all, _categories_factory),
    "GET /categories/{id}": (_handle_get_detail, _categories_factory),
    "PATCH /categories/{id}": (_handle_rename, _categories_factory),
    "DELETE /categories/{id}": (_handle_soft_delete, _categories_factory),
    "PUT /styles/{style_id}/categories/order": (_handle_reorder, _categories_factory),
    "GET /categories/{id}/tracks": (_handle_list_tracks, _categories_factory),
    "POST /categories/{id}/tracks": (_handle_add_track, _categories_factory),
    "DELETE /categories/{id}/tracks/{track_id}": (_handle_remove_track, _categories_factory),
    "POST /triage/blocks": (_create_triage_block, _triage_factory),
    "GET /styles/{style_id}/triage/blocks": (_list_triage_blocks_by_style, _triage_factory),
    "GET /triage/blocks": (_list_triage_blocks_all, _triage_factory),
    "GET /triage/blocks/{id}": (_get_triage_block, _triage_factory),
    "GET /triage/blocks/{id}/buckets/{bucket_id}/tracks": (_list_bucket_tracks, _triage_factory),
    "POST /triage/blocks/{id}/move": (_move_tracks, _triage_factory),
    "POST /triage/blocks/{src_id}/transfer": (_transfer_tracks, _triage_factory),
    "POST /triage/blocks/{id}/finalize": (_finalize_triage_block, _triage_factory),
    "DELETE /triage/blocks/{id}": (_soft_delete_triage_block, _triage_factory),
    "POST /tags": (_handle_create_tag, _tags_factory),
    "GET /tags": (_handle_list_tags, _tags_factory),
    "PATCH /tags/{tag_id}": (_handle_rename_tag, _tags_factory),
    "DELETE /tags/{tag_id}": (_handle_delete_tag, _tags_factory),
    "GET /tracks/{track_id}/tags": (_handle_list_track_tags, _tags_factory),
    "PUT /tracks/{track_id}/tags": (_handle_set_track_tags, _tags_factory),
    "POST /tracks/{track_id}/tags": (_handle_add_track_tag, _tags_factory),
    "DELETE /tracks/{track_id}/tags/{tag_id}": (_handle_remove_track_tag, _tags_factory),
    "POST /playlists": (_handle_create_playlist, _playlists_factory),
    "GET /playlists": (_handle_list_playlists, _playlists_factory),
    "GET /playlists/{id}": (_handle_get_playlist, _playlists_factory),
    "PATCH /playlists/{id}": (_handle_patch_playlist, _playlists_factory),
    "DELETE /playlists/{id}": (_handle_delete_playlist, _playlists_factory),
    "GET /playlists/{id}/tracks": (_handle_list_playlist_tracks, _playlists_factory),
    "POST /playlists/{id}/tracks": (_handle_add_playlist_tracks, _playlists_factory),
    "DELETE /playlists/{id}/tracks/{track_id}": (
        _handle_remove_playlist_track, _playlists_factory,
    ),
    "POST /playlists/{id}/tracks/order": (
        _handle_reorder_playlist_tracks, _playlists_factory,
    ),
    "POST /playlists/{id}/cover/upload-url": (
        _handle_cover_upload_url, _playlists_factory,
    ),
    "POST /playlists/{id}/cover/confirm": (
        _handle_cover_confirm, _playlists_factory,
    ),
    "DELETE /playlists/{id}/cover": (
        _handle_cover_delete, _playlists_factory,
    ),
    "POST /playlists/{id}/tracks/import-spotify": (
        _handle_import_spotify, _playlists_factory,
    ),
    "POST /playlists/{id}/publish": (
        _handle_publish, _playlists_factory,
    ),
    "GET /playlists/{id}/tracks/{track_id}/match-candidates": (
        _handle_match_candidates, _playlists_factory,
    ),
    "POST /playlists/{id}/tracks/{track_id}/match-resolve": (
        _handle_resolve_match, _playlists_factory,
    ),
}
