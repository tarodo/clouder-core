"""Aurora (Data API) repository for the ingest pipeline and the collector API.

`ClouderRepository` composes one mixin per aggregate; callers keep one object.
Every mixin uses only `self._data_api`, so the mixins do not depend on each other.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from ..data_api import DataAPIClient, create_default_data_api_client
from ..settings import get_data_api_settings
from ._base import as_utc_datetime, parse_iso_date, utc_now
from .api_views import ApiViewsMixin
from .catalog_writes import TRACK_MERGE_FIELDS, CatalogWritesMixin, _named_entity_params
from .commands import (
    ConservativeUpdateTrackCmd,
    CreateAlbumCmd,
    CreateIngestRunCmd,
    CreateNamedEntityCmd,
    CreateTrackCmd,
    IdentityMapEntry,
    TrackState,
    UpdateSpotifyResultCmd,
    UpsertIdentityCmd,
    UpsertSourceEntityCmd,
    UpsertSourceRelationCmd,
    UpsertTrackArtistCmd,
    UpsertVendorMatchCmd,
    VendorTrackMatch,
)
from .lineage import LineageMixin, _identity_params
from .runs import IngestRunsMixin
from .spotify import SpotifySearchMixin
from .vendor_match import VendorMatchMixin


class ClouderRepository(
    IngestRunsMixin,
    LineageMixin,
    CatalogWritesMixin,
    SpotifySearchMixin,
    VendorMatchMixin,
    ApiViewsMixin,
):
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def transaction(self) -> AbstractContextManager[str]:
        return self._data_api.transaction()


def create_clouder_repository_from_env() -> ClouderRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return ClouderRepository(data_api)


__all__ = [
    "TRACK_MERGE_FIELDS",
    "ClouderRepository",
    "ConservativeUpdateTrackCmd",
    "CreateAlbumCmd",
    "CreateIngestRunCmd",
    "CreateNamedEntityCmd",
    "CreateTrackCmd",
    "IdentityMapEntry",
    "TrackState",
    "UpdateSpotifyResultCmd",
    "UpsertIdentityCmd",
    "UpsertSourceEntityCmd",
    "UpsertSourceRelationCmd",
    "UpsertTrackArtistCmd",
    "UpsertVendorMatchCmd",
    "VendorTrackMatch",
    "_identity_params",
    "_named_entity_params",
    "as_utc_datetime",
    "create_clouder_repository_from_env",
    "parse_iso_date",
    "utc_now",
]
