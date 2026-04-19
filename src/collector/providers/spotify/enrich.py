"""SpotifyEnricher — wraps SpotifyLookup to expose release_type as EnrichResult.

Currently NOT wired to any handler. Scaffolded so future pipelines can
treat album_type extraction as a generic EnrichProvider call instead of
a Spotify-specific path inside spotify_handler.
"""

from __future__ import annotations

from typing import Any

from ..base import EnrichResult
from .lookup import SpotifyLookup


class SpotifyEnricher:
    vendor_name = "spotify"
    entity_types = ("track",)
    prompt_slug = "spotify_release_type"
    prompt_version = "v1"

    def __init__(self, lookup: SpotifyLookup) -> None:
        self._lookup = lookup

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult:
        if entity_type != "track":
            raise ValueError(
                f"SpotifyEnricher supports entity_type=track, got {entity_type}"
            )

        isrc = context.get("isrc")
        if not isrc:
            return self._wrap(entity_id, {"status": "no_isrc"})

        results = self._lookup.lookup_batch_by_isrc(
            tracks=[{"clouder_track_id": entity_id, "isrc": str(isrc)}],
            correlation_id=correlation_id,
        )
        if not results or not results[0].spotify_id:
            return self._wrap(entity_id, {"status": "not_found"})

        track = results[0].spotify_track or {}
        album_type = (track.get("album") or {}).get("album_type")
        return self._wrap(
            entity_id,
            {"spotify_id": results[0].spotify_id, "album_type": album_type},
        )

    def _wrap(self, entity_id: str, payload: dict[str, Any]) -> EnrichResult:
        return EnrichResult(
            entity_type="track",
            entity_id=entity_id,
            prompt_slug=self.prompt_slug,
            prompt_version=self.prompt_version,
            payload=payload,
        )
