"""Settings: .env loader (no python-dotenv dep) + fixed experiment constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    tavily_api_key: str
    cluster_arn: str
    secret_arn: str
    database: str = "clouder"
    openai_model: str = "gpt-5.4-mini"
    web_search_usd_per_call: float = 0.01
    tavily_usd_per_credit: float = 0.008


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def load_settings(env_path: Path | None = None) -> Settings:
    path = env_path or Path(__file__).resolve().parents[2] / ".env"
    values = _parse_env(path) if path.exists() else {}
    keys = ("OPENAI_API_KEY", "TAVILY_API_KEY", "AURORA_CLUSTER_ARN", "AURORA_SECRET_ARN")
    values = {k: values.get(k) or os.environ.get(k, "") for k in keys}
    missing = [k for k in keys if not values[k]]
    if missing:
        raise ValueError(f"missing keys in {path}: {', '.join(missing)}")
    return Settings(
        openai_api_key=values["OPENAI_API_KEY"],
        tavily_api_key=values["TAVILY_API_KEY"],
        cluster_arn=values["AURORA_CLUSTER_ARN"],
        secret_arn=values["AURORA_SECRET_ARN"],
    )
