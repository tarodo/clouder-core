"""Collaborators of the collector-API routes.

Route modules call these through the module (`deps.X()`), so tests patch
`collector.api.deps` — same pattern as `collector.curation.deps`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from ..beatport_auth import fetch_access_token
from ..beatport_auth import read_credentials as read_beatport_credentials
from ..errors import AppError
from ..providers import registry
from ..repositories import create_clouder_repository_from_env, utc_now
from ..storage import S3Storage, create_default_s3_client


def create_default_sqs_client() -> Any:
    import boto3

    return boto3.client("sqs")


def _auto_ingest_repository() -> Any:
    from ..auto_ingest_repository import AutoIngestRepository
    from ..data_api import create_default_data_api_client
    from ..settings import get_data_api_settings

    settings = get_data_api_settings()
    if not settings.is_configured:
        raise AppError(
            status_code=503, error_code="db_not_configured", message="Database is not configured"
        )
    return AutoIngestRepository(
        create_default_data_api_client(
            resource_arn=str(settings.aurora_cluster_arn),
            secret_arn=str(settings.aurora_secret_arn),
            database=settings.aurora_database,
        )
    )


def _invoke_auto_ingest(payload: Mapping[str, Any]) -> None:
    """Asynchronous: replan after a save, or a manual run."""
    import boto3

    name = os.environ.get("AUTO_INGEST_FUNCTION_NAME", "").strip()
    if not name:
        raise AppError(
            status_code=503,
            error_code="config_error",
            message="AUTO_INGEST_FUNCTION_NAME is not set",
        )
    boto3.client("lambda").invoke(
        FunctionName=name, InvocationType="Event", Payload=json.dumps(dict(payload)).encode()
    )


__all__ = [
    "S3Storage",
    "_auto_ingest_repository",
    "_invoke_auto_ingest",
    "create_clouder_repository_from_env",
    "create_default_s3_client",
    "create_default_sqs_client",
    "fetch_access_token",
    "read_beatport_credentials",
    "registry",
    "utc_now",
]
