"""Environment-driven configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    xai_api_key: str | None = None
    perplexity_api_key: str | None = None

    anthropic_model: str = "claude-sonnet-4-6"
    xai_model: str = "grok-4"
    perplexity_model: str = "sonar"

    concurrency: int = 4
    request_timeout: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        env_nested_delimiter=None,
        extra="ignore",
    )


def available_vendor_names(s: Settings) -> list[str]:
    """Return the vendors for which an API key is configured."""
    out: list[str] = []
    if s.anthropic_api_key:
        out.append("anthropic")
    if s.xai_api_key:
        out.append("xai")
    if s.perplexity_api_key:
        out.append("perplexity")
    return out
