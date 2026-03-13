"""Typed runtime settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class WorkerSettings(_SettingsBase):
    raw_bucket_name: str = Field(alias="RAW_BUCKET_NAME")
    raw_prefix: str = Field(default="raw/bp/releases", alias="RAW_PREFIX")
    ai_search_queue_url: str = Field(default="", alias="AI_SEARCH_QUEUE_URL")


class SearchWorkerSettings(_SettingsBase):
    perplexity_api_key: str = Field(alias="PERPLEXITY_API_KEY")


class MigrationSettings(_SettingsBase):
    aurora_secret_arn: str = Field(alias="AURORA_SECRET_ARN")
    aurora_writer_endpoint: str = Field(alias="AURORA_WRITER_ENDPOINT")
    aurora_database: str = Field(alias="AURORA_DATABASE")
    aurora_port: int = Field(default=5432, alias="AURORA_PORT")


class LoggingSettings(_SettingsBase):
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()


@lru_cache
def get_migration_settings() -> MigrationSettings:
    return MigrationSettings()


@lru_cache
def get_data_api_settings() -> DataApiSettings:
    return DataApiSettings()


@lru_cache
def get_logging_settings() -> LoggingSettings:
    return LoggingSettings()


@lru_cache
def get_search_worker_settings() -> SearchWorkerSettings:
    return SearchWorkerSettings()


def reset_settings_cache() -> None:
    get_api_settings.cache_clear()
    get_worker_settings.cache_clear()
    get_migration_settings.cache_clear()
    get_data_api_settings.cache_clear()
    get_logging_settings.cache_clear()
    get_search_worker_settings.cache_clear()
