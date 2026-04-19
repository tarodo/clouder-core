"""Typed runtime settings loaded from environment variables."""

from __future__ import annotations

import functools
import json
import os

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@functools.lru_cache(maxsize=32)
def _fetch_secret_string(secret_arn: str) -> str:
    """Fetch SecretString from AWS Secrets Manager.

    Cached per ARN for the container lifetime — efficient, but secrets
    rotated via AWS are not picked up until container recycles. Acceptable
    for our use case where Perplexity/Spotify keys are long-lived.
    """
    import boto3

    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_arn)
    value = resp.get("SecretString")
    if not isinstance(value, str) or not value:
        if resp.get("SecretBinary"):
            raise RuntimeError(
                f"secret is SecretBinary, expected SecretString (arn={secret_arn})"
            )
        raise RuntimeError(f"secret is empty or not a string (arn={secret_arn})")
    return value


def _resolve_simple_secret(env_key: str, arn_env_key: str) -> str:
    """Resolve a scalar secret with precedence: direct env > SSM > Secrets Manager.

    For a given env_key "PERPLEXITY_API_KEY" the helper checks:
        1. env var PERPLEXITY_API_KEY (direct value)
        2. env var PERPLEXITY_API_KEY_SSM_PARAMETER (SSM param name)
        3. env var PERPLEXITY_API_KEY_SECRET_ARN (legacy Secrets Manager)

    Returns "" when none of them resolve.
    """
    from collector import secrets

    direct = os.environ.get(env_key, "").strip()
    if direct:
        return direct

    ssm_env_key = f"{env_key}_SSM_PARAMETER"
    ssm_name = os.environ.get(ssm_env_key, "").strip()
    if ssm_name:
        return secrets._fetch_ssm_parameter(ssm_name)

    arn = os.environ.get(arn_env_key, "").strip()
    if arn:
        return _fetch_secret_string(arn)

    return ""


def _resolve_spotify_credentials() -> tuple[str, str]:
    """Resolve (client_id, client_secret) with precedence: direct env > SSM > SM.

    SSM layout stores client_id and client_secret as TWO SecureString parameters
    to avoid JSON marshalling issues and to allow per-field rotation.
    """
    from collector import secrets

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret

    ssm_id_name = os.environ.get("SPOTIFY_CLIENT_ID_SSM_PARAMETER", "").strip()
    ssm_secret_name = os.environ.get("SPOTIFY_CLIENT_SECRET_SSM_PARAMETER", "").strip()
    # All-or-nothing: if only one SSM name is set, fall through to SM to avoid
    # silently returning a half-resolved credential pair.
    if ssm_id_name and ssm_secret_name:
        client_id = client_id or secrets._fetch_ssm_parameter(ssm_id_name)
        client_secret = client_secret or secrets._fetch_ssm_parameter(ssm_secret_name)
        return client_id, client_secret

    arn = os.environ.get("SPOTIFY_CREDENTIALS_SECRET_ARN", "").strip()
    if arn:
        raw = _fetch_secret_string(arn)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"spotify credentials secret is not valid JSON (arn={arn}): {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"spotify credentials secret JSON must be an object (arn={arn})"
            )
        client_id = client_id or str(data.get("client_id", ""))
        client_secret = client_secret or str(data.get("client_secret", ""))

    return client_id, client_secret


class _SettingsBase(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )


class DataApiSettings(_SettingsBase):
    aurora_cluster_arn: str | None = Field(default=None, alias="AURORA_CLUSTER_ARN")
    aurora_secret_arn: str | None = Field(default=None, alias="AURORA_SECRET_ARN")
    aurora_database: str = Field(default="postgres", alias="AURORA_DATABASE")

    @property
    def is_configured(self) -> bool:
        return bool(self.aurora_cluster_arn and self.aurora_secret_arn)


class ApiSettings(_SettingsBase):
    raw_bucket_name: str = Field(alias="RAW_BUCKET_NAME")
    raw_prefix: str = Field(default="raw/bp/releases", alias="RAW_PREFIX")
    beatport_api_base_url: str = Field(
        default="https://api.beatport.com/v4/catalog", alias="BEATPORT_API_BASE_URL"
    )
    canonicalization_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "CANONICALIZATION_ENABLED", "CANONICALIZE_ENABLED"
        ),
    )
    canonicalization_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CANONICALIZATION_QUEUE_URL", "CANONICALIZE_QUEUE_URL"
        ),
    )
    ai_search_enabled: bool = Field(default=False, alias="AI_SEARCH_ENABLED")
    ai_search_queue_url: str = Field(default="", alias="AI_SEARCH_QUEUE_URL")
    spotify_search_enabled: bool = Field(default=False, alias="SPOTIFY_SEARCH_ENABLED")
    spotify_search_queue_url: str = Field(default="", alias="SPOTIFY_SEARCH_QUEUE_URL")


class WorkerSettings(_SettingsBase):
    raw_bucket_name: str = Field(alias="RAW_BUCKET_NAME")
    raw_prefix: str = Field(default="raw/bp/releases", alias="RAW_PREFIX")
    ai_search_queue_url: str = Field(default="", alias="AI_SEARCH_QUEUE_URL")
    spotify_search_queue_url: str = Field(default="", alias="SPOTIFY_SEARCH_QUEUE_URL")


class SearchWorkerSettings(_SettingsBase):
    perplexity_api_key: str = Field(default="")
    ai_flag_confidence_threshold: float = Field(
        default=0.6, alias="AI_FLAG_CONFIDENCE_THRESHOLD"
    )


class SpotifyWorkerSettings(_SettingsBase):
    spotify_client_id: str = Field(default="")
    spotify_client_secret: str = Field(default="")
    raw_bucket_name: str = Field(alias="RAW_BUCKET_NAME")
    spotify_raw_prefix: str = Field(default="raw/sp/tracks", alias="SPOTIFY_RAW_PREFIX")
    spotify_search_queue_url: str = Field(default="", alias="SPOTIFY_SEARCH_QUEUE_URL")


class MigrationSettings(_SettingsBase):
    aurora_secret_arn: str = Field(default="", alias="AURORA_SECRET_ARN")
    aurora_writer_endpoint: str = Field(alias="AURORA_WRITER_ENDPOINT")
    aurora_database: str = Field(alias="AURORA_DATABASE")
    aurora_port: int = Field(default=5432, alias="AURORA_PORT")
    aurora_auth_mode: str = Field(default="password", alias="AURORA_AUTH_MODE")
    aurora_db_user: str = Field(default="", alias="AURORA_DB_USER")


class LoggingSettings(_SettingsBase):
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@functools.lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()


@functools.lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


@functools.lru_cache
def get_migration_settings() -> MigrationSettings:
    return MigrationSettings()


@functools.lru_cache
def get_data_api_settings() -> DataApiSettings:
    return DataApiSettings()


@functools.lru_cache
def get_logging_settings() -> LoggingSettings:
    return LoggingSettings()


@functools.lru_cache
def get_search_worker_settings() -> SearchWorkerSettings:
    key = _resolve_simple_secret(
        "PERPLEXITY_API_KEY", "PERPLEXITY_API_KEY_SECRET_ARN"
    )
    return SearchWorkerSettings(perplexity_api_key=key)


@functools.lru_cache
def get_spotify_worker_settings() -> SpotifyWorkerSettings:
    client_id, client_secret = _resolve_spotify_credentials()
    return SpotifyWorkerSettings(
        spotify_client_id=client_id,
        spotify_client_secret=client_secret,
    )


def reset_settings_cache() -> None:
    get_api_settings.cache_clear()
    get_worker_settings.cache_clear()
    get_migration_settings.cache_clear()
    get_data_api_settings.cache_clear()
    get_logging_settings.cache_clear()
    get_search_worker_settings.cache_clear()
    get_spotify_worker_settings.cache_clear()
    if hasattr(_fetch_secret_string, "cache_clear"):
        _fetch_secret_string.cache_clear()

    from collector import secrets as _secrets_module

    _secrets_module.reset_cache()
