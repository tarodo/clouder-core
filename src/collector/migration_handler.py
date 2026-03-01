"""Lambda handler that executes Alembic migrations against Aurora."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote_plus

from alembic import command
from alembic.config import Config
from pydantic import ValidationError as PydanticValidationError

from .logging_utils import log_event
from .schemas import MigrationCommand, validation_error_message
from .settings import get_migration_settings


def lambda_handler(event: Mapping[str, Any] | None, context: Any) -> dict[str, Any]:
    del context
    payload = event if isinstance(event, Mapping) else {}
    try:
        command_payload = MigrationCommand.model_validate(payload)
    except PydanticValidationError as exc:
        return {
            "status": "error",
            "message": validation_error_message(exc),
            "action": str(payload.get("action", "")).strip().lower(),
        }

    alembic_url = _build_alembic_database_url()
    os.environ["ALEMBIC_DATABASE_URL"] = alembic_url

    root_dir = Path(__file__).resolve().parent.parent
    alembic_ini_path = root_dir / "alembic.ini"
    script_location = root_dir / "db_migrations"
    if not alembic_ini_path.exists() or not script_location.exists():
        raise RuntimeError("Alembic files are missing from Lambda artifact")

    config = Config(str(alembic_ini_path))
    config.set_main_option("script_location", str(script_location))

    started_at = datetime.now(timezone.utc)
    log_event(
        "INFO",
        "migration_started",
        status_code=200,
        error_code="",
    )

    command.upgrade(config, command_payload.revision)

    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    log_event(
        "INFO",
        "migration_completed",
        status_code=200,
        duration_ms=duration_ms,
    )

    return {
        "status": "ok",
        "action": command_payload.action,
        "revision": command_payload.revision,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "duration_ms": duration_ms,
    }


def _build_alembic_database_url() -> str:
    settings = get_migration_settings()
    secret = _read_secret(settings.aurora_secret_arn)
    username = str(secret.get("username", "")).strip()
    password = str(secret.get("password", "")).strip()
    if not username or not password:
        raise RuntimeError("username/password are missing in Aurora secret")

    return (
        f"postgresql+psycopg://{quote_plus(username)}:{quote_plus(password)}"
        f"@{settings.aurora_writer_endpoint}:{settings.aurora_port}/{settings.aurora_database}?sslmode=require"
    )


def _read_secret(secret_arn: str) -> dict[str, Any]:
    import boto3

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    secret_value = response.get("SecretString")
    if not isinstance(secret_value, str) or not secret_value.strip():
        raise RuntimeError("Aurora secret is empty")

    try:
        parsed = json.loads(secret_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Aurora secret payload is not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("Aurora secret payload must be a JSON object")
    return parsed
