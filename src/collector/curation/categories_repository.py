"""Aurora Data API repository for spec-C categories.

Tenancy: every method takes `user_id` and includes it in WHERE.
Cross-user access yields zero rows (mapped to 404 by the handler).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from collector.data_api import DataAPIClient
from collector.settings import get_data_api_settings

from . import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
    PaginatedResult,
    utc_now,
)


@dataclass(frozen=True)
class CategoryRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    normalized_name: str
    position: int
    track_count: int
    created_at: str  # ISO string from Data API
    updated_at: str


@dataclass(frozen=True)
class TrackInCategoryRow:
    track: Mapping[str, Any]
    added_at: str
    source_triage_block_id: str | None


class CategoriesRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # Methods filled in by Tasks 6–13.


def create_default_categories_repository() -> CategoriesRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return CategoriesRepository(data_api=data_api)
