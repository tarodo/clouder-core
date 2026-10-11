"""Lambda handler for the user-curation surface (spec-C/D/E).

`_ROUTE_TABLE` is the single source of truth: each `routeKey` maps to a
`(handler, repo_factory)` tuple. spec-D and spec-E will append entries.
Every route is JWT-gated by the API Gateway Lambda Authorizer (spec-A);
`user_id` is read from `event.requestContext.authorizer.lambda.user_id`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .curation import CurationError
from .curation.deps import (
    _categories_factory,
    _comments_factory,
    _playlists_factory,
    _tags_factory,
    _triage_factory,
)
from .curation.http import (
    _curation_error_response,
    _error,
    _extract_correlation_id,
    _user_id_or_none,
)
from .curation.routes_categories import (
    _handle_add_track,
    _handle_create_category,
    _handle_get_detail,
    _handle_list_all,
    _handle_list_by_style,
    _handle_list_tracks,
    _handle_remove_track,
    _handle_rename,
    _handle_reorder,
    _handle_soft_delete,
)
from .curation.routes_playlists import (
    _handle_add_playlist_tracks,
    _handle_cover_confirm,
    _handle_cover_delete,
    _handle_cover_upload_url,
    _handle_create_playlist,
    _handle_delete_playlist,
    _handle_export_playlist,
    _handle_get_playlist,
    _handle_import_spotify,
    _handle_import_spotify_playlist,
    _handle_list_playlist_comments,
    _handle_list_playlist_tracks,
    _handle_list_playlists,
    _handle_list_track_comments,
    _handle_match_candidates,
    _handle_patch_playlist,
    _handle_publish,
    _handle_publish_ytmusic,
    _handle_remove_playlist_track,
    _handle_reorder_playlist_tracks,
    _handle_resolve_match,
)
from .curation.routes_tags import (
    _handle_add_track_tag,
    _handle_create_tag,
    _handle_delete_tag,
    _handle_list_tags,
    _handle_list_track_tags,
    _handle_remove_track_tag,
    _handle_rename_tag,
    _handle_set_track_tags,
)
from .curation.routes_triage import (
    _create_triage_block,
    _finalize_triage_block,
    _get_triage_block,
    _list_bucket_tracks,
    _list_triage_blocks_all,
    _list_triage_blocks_by_style,
    _move_tracks,
    _soft_delete_triage_block,
    _transfer_tracks,
)
from .logging_utils import log_event


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
    except Exception as exc:
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
    "GET /tracks/{track_id}/comments": (_handle_list_track_comments, _comments_factory),
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
    "POST /playlists/import-spotify-playlist": (
        _handle_import_spotify_playlist, _playlists_factory,
    ),
    "POST /playlists/{id}/tracks/import-spotify": (
        _handle_import_spotify, _playlists_factory,
    ),
    "POST /playlists/{id}/publish": (
        _handle_publish, _playlists_factory,
    ),
    "POST /playlists/{id}/publish-ytmusic": (
        _handle_publish_ytmusic, _playlists_factory,
    ),
    "GET /playlists/{id}/tracks/{track_id}/match-candidates": (
        _handle_match_candidates, _playlists_factory,
    ),
    "POST /playlists/{id}/tracks/{track_id}/match-resolve": (
        _handle_resolve_match, _playlists_factory,
    ),
    "GET /playlists/{id}/comments": (
        _handle_list_playlist_comments, _playlists_factory,
    ),
    "GET /playlists/{id}/export": (
        _handle_export_playlist, _playlists_factory,
    ),
}
