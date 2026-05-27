"""HTTP handlers for auto-enrichment config (artists)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from ..data_api import create_default_data_api_client
from ..errors import ValidationError
from ..settings import get_data_api_settings
from .auto_messages import AutoEnrichConfigIn
from .auto_repository import AutoEnrichRepository

_KIND = "artists"


def _build_repository() -> AutoEnrichRepository:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return AutoEnrichRepository(data_api=client)


def _extract_user_id(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if not isinstance(rc, Mapping):
        return None
    authz = rc.get("authorizer")
    if not isinstance(authz, Mapping):
        return None
    ctx = authz.get("lambda")
    if isinstance(ctx, Mapping):
        return ctx.get("user_id")
    return None


def _options() -> dict[str, Any]:
    """Same payload shape the manual enqueue form consumes."""
    from .prompts import list_prompt_versions, load_builtin_prompts

    load_builtin_prompts()
    return {
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "prompt_versions": list_prompt_versions(),
        "default_models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "merge": {"vendor": "deepseek", "default_model": "deepseek-v4-flash"},
    }


def _default_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "vendors": [],
        "models": {},
        "prompt_slug": None,
        "prompt_version": None,
        "merge_vendor": "deepseek",
        "merge_model": None,
    }


def handle_get_auto_config(event: Mapping[str, Any]) -> tuple[int, dict]:
    del event  # static + singleton config
    repo = _build_repository()
    saved = repo.get_config(_KIND)
    if saved is None:
        config = _default_config()
    else:
        config = {
            "enabled": bool(saved["enabled"]),
            "vendors": saved["vendors"],
            "models": saved["models"],
            "prompt_slug": saved.get("prompt_slug"),
            "prompt_version": saved.get("prompt_version"),
            "merge_vendor": saved.get("merge_vendor") or "deepseek",
            "merge_model": saved.get("merge_model"),
        }
    return 200, {"config": config, "options": _options()}


def handle_put_auto_config(event: Mapping[str, Any]) -> tuple[int, dict]:
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")
    try:
        req = AutoEnrichConfigIn.model_validate(body)
    except PydanticValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc

    repo = _build_repository()
    repo.upsert_config(
        kind=_KIND,
        enabled=req.enabled,
        vendors=list(req.vendors),
        models=dict(req.models),
        prompt_slug=req.prompt_slug,
        prompt_version=req.prompt_version,
        merge_vendor=req.merge_vendor,
        merge_model=req.merge_model,
        user_id=_extract_user_id(event),
    )
    return 204, {}
