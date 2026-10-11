"""Playlist routes (spec-E): CRUD, tracks, covers, import, publish, comments, export."""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from ..comments.dispatch import try_dispatch_comment_collection
from ..logging_utils import log_event
from ..providers.ytmusic.normalize import result_to_ref
from . import (
    CoverMissingError,
    CoverTooLargeError,
    InvalidSpotifyRefError,
    NotFoundError,
    PlaylistNotFoundError,
    SpotifyNotFoundError,
    TrackNotInUserScopeError,
    ValidationError,
    deps,
    utc_now,
)
from .http import _error, _json_response, _parse_body, _parse_pagination
from .playlists_repository import (
    ImportTrackInput,
    PlaylistsRepository,
)
from .playlists_service import (
    MAX_COVER_BYTES,
    MAX_IMPORT_PLAYLIST_TRACKS,
    MAX_NAME_LENGTH,
    normalize_playlist_name,
    parse_spotify_playlist_ref,
    parse_spotify_ref,
    validate_description,
    validate_playlist_name,
)
from .schemas import (
    AddTracksIn,
    CoverUploadUrlIn,
    CreatePlaylistIn,
    ImportSpotifyPlaylistIn,
    ImportSpotifyTracksIn,
    PatchPlaylistIn,
    PublishPlaylistIn,
    ReorderPlaylistTracksIn,
    ResolveMatchIn,
)


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
        "ytmusic_playlist_id": row.ytmusic_playlist_id,
        "ytmusic_last_published_at": row.ytmusic_last_published_at,
        "ytmusic_needs_republish": row.ytmusic_needs_republish,
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
        return deps._build_s3_storage()
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
        "key_name": getattr(row, "key_name", None),
        "key_camelot": getattr(row, "key_camelot", None),
        "spotify_release_date": getattr(row, "spotify_release_date", None),
        "is_ai_suspected": bool(getattr(row, "is_ai_suspected", False)),
        "artists": list(getattr(row, "artists", ())),
        "label": getattr(row, "label", None),
        "beatport_track_id": getattr(row, "beatport_track_id", None),
        "beatport_slug": getattr(row, "beatport_slug", None),
        "tags": [
            {"id": t.tag_id, "name": t.name, "color": t.color}
            for t in getattr(row, "tags", ())
        ],
        "ytmusic": getattr(row, "ytmusic", None),
    }


def _project_candidate(c: dict) -> dict[str, Any] | None:
    ref = c.get("ref") or {}
    vt = result_to_ref(ref)
    vid = vt.vendor_track_id if vt else str(ref.get("videoId") or "")
    if not vid:
        return None
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
         "candidates": [p for c in review.candidates
                        if (p := _project_candidate(c)) is not None]},
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
        video_id = body.vendor_track_id
        assert video_id is not None  # ResolveMatchIn requires it on accept
        review = repo.get_open_review(track_id=track_id, vendor=body.vendor)
        payload: dict[str, Any] = {
            "videoId": video_id,
            "url": f"https://music.youtube.com/watch?v={video_id}",
            "source": "manual_url",
        }
        if review is not None:
            for c in review.candidates:
                ref = c.get("ref") or {}
                if str(ref.get("videoId") or "") == video_id:
                    payload = ref
                    break
        repo.resolve_review_accept(
            clouder_track_id=track_id, vendor=body.vendor,
            vendor_track_id=body.vendor_track_id, payload=payload, now=utc_now(),
        )
        if body.vendor == "ytmusic":
            try_dispatch_comment_collection(
                track_id=track_id, video_id=video_id, platform="youtube"
            )
    else:
        repo.resolve_review_reject(
            clouder_track_id=track_id, vendor=body.vendor, now=utc_now(),
        )

    log_event(
        "INFO", "match_review_resolved",
        correlation_id=correlation_id, user_id=user_id,
        playlist_id=pid, track_id=track_id, vendor=body.vendor, action=body.action,
    )
    status = repo.fetch_ytmusic_status([track_id]).get(track_id)
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
    storage = deps._build_s3_storage() if row.cover_s3_key else None
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
    storage = deps._build_s3_storage() if row.cover_s3_key else None
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
    tags_repo = deps.create_default_tags_repository()
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


def _handle_cover_upload_url(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = CoverUploadUrlIn.model_validate(_parse_body(event))
    # Ownership check: 404 if not user's playlist.
    if repo.get(user_id=user_id, playlist_id=pid) is None:
        raise PlaylistNotFoundError()
    storage = deps._build_s3_storage()
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
    storage = deps._build_s3_storage()
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

    sp_client = deps._build_spotify_user_client(user_id, correlation_id)

    payloads = []
    for sid in spotify_ids:
        try:
            payloads.append(sp_client.get_track(sid))
        except SpotifyNotFoundError as exc:
            skipped.append({"ref": sid, "reason": "not_found"})
            log_event(
                "WARNING", "playlist_spotify_import_failed",
                correlation_id=correlation_id, user_id=user_id,
                spotify_id=sid, reason=str(exc),
            )

    inputs = [
        ImportTrackInput(
            spotify_id=p.id, title=p.name, isrc=p.isrc,
            length_ms=p.duration_ms,
            artists=[a.name for a in p.artists if a.name],
        )
        for p in payloads
    ]
    track_ids = repo.import_tracks_batch(
        user_id=user_id, tracks=inputs, now=utc_now(),
    )
    added_details = [
        {"track_id": tid, "spotify_id": p.id, "title": p.name}
        for tid, p in zip(track_ids, payloads)
    ]

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


def _handle_import_spotify_playlist(event, repo, user_id, correlation_id):
    body = ImportSpotifyPlaylistIn.model_validate(_parse_body(event))
    # InvalidSpotifyRefError is a CurationError with http_status=400; let it
    # propagate to lambda_handler's generic CurationError handling rather
    # than wrapping it in ValidationError (422), which would misreport a
    # malformed ref as a 422 instead of a 400.
    playlist_sid = parse_spotify_playlist_ref(body.spotify_ref)

    sp_client = deps._build_spotify_user_client(user_id, correlation_id)
    try:
        sp_name = sp_client.get_playlist_name(playlist_sid)
        payloads = sp_client.get_playlist_tracks(
            playlist_sid, limit=MAX_IMPORT_PLAYLIST_TRACKS + 1,
        )
    except SpotifyNotFoundError:
        # The Spotify playlist doesn't exist or isn't accessible to this
        # user — surface the route's documented 404 rather than letting
        # SpotifyNotFoundError's inherited 502 (upstream error) leak
        # through, which would misreport a client-facing "not found" as
        # a server-side Spotify failure.
        raise PlaylistNotFoundError()
    truncated = len(payloads) > MAX_IMPORT_PLAYLIST_TRACKS
    if truncated:
        payloads = payloads[:MAX_IMPORT_PLAYLIST_TRACKS]

    name = (body.name or sp_name or "Imported playlist").strip()[:MAX_NAME_LENGTH]
    validate_playlist_name(name)
    normalized = normalize_playlist_name(name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    playlist_id = str(uuid.uuid4())
    repo.create(
        user_id=user_id, playlist_id=playlist_id, name=name,
        normalized_name=normalized, description=None, is_public=True,
        now=utc_now(),
    )

    try:
        inputs = [
            ImportTrackInput(
                spotify_id=p.id, title=p.name, isrc=p.isrc,
                length_ms=p.duration_ms,
                artists=[a.name for a in p.artists if a.name],
            )
            for p in payloads
        ]
        track_ids = repo.import_tracks_batch(
            user_id=user_id, tracks=inputs, now=utc_now(),
        )
        result = repo.append_tracks(
            user_id=user_id, playlist_id=playlist_id,
            track_ids=track_ids, now=utc_now(),
        )
    except Exception:
        # Don't leave an orphan, empty playlist behind if anything after
        # create() fails — it would block retry with a 409 name conflict.
        with contextlib.suppress(Exception):
            repo.soft_delete(user_id=user_id, playlist_id=playlist_id, now=utc_now())
        raise
    _enqueue_ytmusic(repo, result.added_track_ids, correlation_id)

    log_event(
        "INFO", "playlist_spotify_playlist_imported",
        correlation_id=correlation_id, user_id=user_id, playlist_id=playlist_id,
        imported=len(result.added_track_ids), truncated=truncated,
    )
    return _json_response(
        201,
        {
            "playlist_id": playlist_id,
            "name": name,
            "imported": len(result.added_track_ids),
            "skipped": len(result.skipped_duplicates),
            "truncated": truncated,
            "total": len(track_ids),
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_publish_ytmusic(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = PublishPlaylistIn.model_validate(_parse_body(event))

    yt_client = deps._build_ytmusic_user_client(user_id, correlation_id)
    storage = deps._build_s3_storage()

    from .ytmusic_publish_service import YtmusicPublishService

    svc = YtmusicPublishService(repo=repo, ytmusic_client=yt_client, storage=storage)
    result = svc.publish(
        user_id=user_id, playlist_id=pid,
        confirm_overwrite=body.confirm_overwrite,
    )
    return _json_response(
        200,
        {
            "ytmusic_playlist_id": result.ytmusic_playlist_id,
            "ytmusic_url": result.ytmusic_url,
            "skipped_tracks": result.skipped,
            "cover_failed": result.cover_failed,
            "published_at": result.published_at,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_publish(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = PublishPlaylistIn.model_validate(_parse_body(event))

    sp_client = deps._build_spotify_user_client(user_id, correlation_id)
    storage = deps._build_s3_storage()

    from .playlists_publish_service import (
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


def _handle_export_playlist(event, repo, user_id, correlation_id):
    """Full playlist export: tracks + YouTube comments + artist/label enrichment.

    Two-repo handler (cf. _handle_list_playlist_comments): the injected repo is
    the PlaylistsRepository; the comments repo is built separately. Enrichment is
    read in bulk off the same Data API client, so the payload costs a fixed
    number of statements no matter how many artists the playlist spans.
    """
    from .playlist_export import (
        build_playlist_export,
        collect_entity_ids,
        fetch_entity_info,
    )

    # Keep the export small: the top comments (by collection rank) per track.
    max_comments = 15

    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    playlist = repo.get(user_id=user_id, playlist_id=pid)
    if playlist is None:
        raise PlaylistNotFoundError()

    rows, _total = repo.list_tracks(
        user_id=user_id, playlist_id=pid, limit=10_000, offset=0,
    )

    comments_by_track: dict[str, list[dict[str, Any]]] = {}
    comments_repo = deps._comments_factory()
    if comments_repo is not None and rows:
        by_track = comments_repo.list_comments_for_tracks(
            track_ids=[r.track_id for r in rows],
            platform="youtube",
            limit_per_track=max_comments,
        )
        for tid, (_collection, comments) in by_track.items():
            # author_avatar_url is dropped — avatar URLs are noise in an export.
            comments_by_track[tid] = [
                {
                    "author": c.author_name,
                    "text": c.text,
                    "like_count": c.like_count,
                    "published_at": (
                        c.published_at.isoformat()
                        if hasattr(c.published_at, "isoformat")
                        else c.published_at
                    ),
                }
                for c in comments
            ]

    artist_ids, label_ids = collect_entity_ids(rows)
    artist_info, label_info = fetch_entity_info(
        repo.data_api, artist_ids=artist_ids, label_ids=label_ids,
    )

    payload = build_playlist_export(
        playlist_name=playlist.name,
        track_rows=rows,
        comments_by_track=comments_by_track,
        artist_info=artist_info,
        label_info=label_info,
    )
    log_event(
        "INFO", "playlist_exported",
        correlation_id=correlation_id, user_id=user_id, playlist_id=pid,
    )
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _serialize_comment(c) -> dict[str, Any]:
    return {
        "author_name": c.author_name,
        "author_avatar_url": c.author_avatar_url,
        "text": c.text,
        "like_count": c.like_count,
        "published_at": (
            c.published_at.isoformat()
            if hasattr(c.published_at, "isoformat")
            else c.published_at
        ),
    }


def _handle_list_track_comments(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    track_id = pp.get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")

    qs = event.get("queryStringParameters") or {}
    platform = (qs.get("platform") or "youtube").strip() or "youtube"
    try:
        limit = int(qs.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 100))

    collection, comments = repo.list_comments(
        track_id=track_id, platform=platform, limit=limit
    )
    if collection is None:
        return _json_response(
            200,
            {"status": "pending", "comment_count": 0, "video_url": None, "comments": []},
            correlation_id,
        )

    video_url = (
        f"https://www.youtube.com/watch?v={collection.external_video_id}"
        if platform == "youtube"
        else None
    )
    return _json_response(
        200,
        {
            "status": collection.status,
            "comment_count": collection.comment_count,
            "video_url": video_url,
            "comments": [_serialize_comment(c) for c in comments],
        },
        correlation_id,
    )


def _handle_list_playlist_comments(event, playlists_repo, user_id, correlation_id):
    # Two-repo handler (cf. _handle_publish_ytmusic): the route's factory is
    # _playlists_factory, so the injected repo is the PlaylistsRepository (used
    # for the user-scoped track listing). The comments repo is built separately
    # via deps._comments_factory() below. Note: in the single-track sibling
    # _handle_list_track_comments the injected repo IS the comments repo.
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")

    qs = event.get("queryStringParameters") or {}
    platform = (qs.get("platform") or "youtube").strip() or "youtube"

    rows, _total = playlists_repo.list_tracks(
        user_id=user_id, playlist_id=pid, limit=10_000, offset=0
    )

    comments_repo = deps._comments_factory()
    if comments_repo is None:
        return _error(503, "db_not_configured", "Database not configured", correlation_id)

    track_ids = [r.track_id for r in rows]
    by_track = comments_repo.list_comments_for_tracks(
        track_ids=track_ids, platform=platform, limit_per_track=100
    )

    tracks_out = []
    for r in rows:
        tid = r.track_id
        if tid not in by_track:
            tracks_out.append({
                "track_id": tid,
                "status": "pending",
                "comment_count": 0,
                "video_url": None,
                "comments": [],
            })
        else:
            collection, comments = by_track[tid]
            video_url = (
                f"https://www.youtube.com/watch?v={collection.external_video_id}"
                if platform == "youtube"
                else None
            )
            tracks_out.append({
                "track_id": tid,
                "status": collection.status,
                "comment_count": collection.comment_count,
                "video_url": video_url,
                "comments": [_serialize_comment(c) for c in comments],
            })

    return _json_response(
        200,
        {"tracks": tracks_out, "correlation_id": correlation_id},
        correlation_id,
    )
