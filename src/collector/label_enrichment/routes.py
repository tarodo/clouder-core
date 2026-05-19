"""HTTP handlers for label enrichment.

The handlers stay framework-agnostic: they accept the API Gateway event
dict and return a (status, body) tuple. `collector.handler` wraps them
in the shared _json_response shape.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from ..data_api import create_default_data_api_client
from ..errors import ValidationError
from ..settings import get_data_api_settings
from .messages import EnrichLabelsRequestIn
from .prompts import get_prompt, load_builtin_prompts
from .repository import LabelEnrichmentRepository, RunSpec


def _build_repository() -> LabelEnrichmentRepository:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return LabelEnrichmentRepository(data_api=client)


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("LABEL_ENRICHMENT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("LABEL_ENRICHMENT_QUEUE_URL is required")
    return url


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


def handle_post_enrich(event: Mapping[str, Any]) -> tuple[int, dict]:
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")
    try:
        req = EnrichLabelsRequestIn.model_validate(body)
    except PydanticValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc

    load_builtin_prompts()
    try:
        get_prompt(req.prompt_slug)
    except KeyError as exc:
        raise ValidationError(f"unknown prompt_slug: {req.prompt_slug}") from exc

    repo = _build_repository()
    sqs = _build_sqs_client()
    queue_url = _queue_url()

    label_ids: list[tuple[str, str, str]] = []  # (label_id, label_name, style)
    for item in req.labels:
        if item.label_id:
            row = repo.get_label_by_id(item.label_id)
            if row is None:
                raise ValidationError(f"label_id not found: {item.label_id}")
            resolved_id = row["id"]
            resolved_name = row["name"]
            # If caller passed style, prefer it. Otherwise derive from tracks.
            # If no tracks, fall back to "music" so vendors get a non-empty hint.
            resolved_style = (
                item.style
                or repo.derive_style_for_label(resolved_id)
                or "music"
            )
        else:
            # label_name path — must have style per the model_validator
            resolved_id = repo.upsert_label_by_name(item.label_name)
            resolved_name = item.label_name
            resolved_style = item.style  # validated non-empty by model_validator
        label_ids.append((resolved_id, resolved_name, resolved_style))

    spec = RunSpec(
        prompt_slug=req.prompt_slug,
        prompt_version=req.prompt_version,
        vendors=list(req.vendors),
        models=dict(req.models),
        merge_vendor=req.merge_vendor,
        merge_model=req.merge_model,
        requested_labels=len(req.labels),
        created_by_user_id=_extract_user_id(event),
    )
    run_id = repo.create_run(spec)

    for lid, name, style in label_ids:
        msg = {
            "run_id": run_id,
            "label_id": lid,
            "label_name": name,
            "style": style,
        }
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(msg))

    return 202, {"run_id": run_id, "queued_labels": len(req.labels)}


def handle_get_run(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    run_id = (path.get("run_id") or "").strip()
    if not run_id:
        raise ValidationError("run_id is required")
    repo = _build_repository()
    row = repo.get_run(run_id)
    if row is None:
        return 404, {"error_code": "not_found", "message": "run not found"}
    row["cells"] = repo.list_cells_for_run(run_id)
    return 200, row


def handle_get_label(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    repo = _build_repository()
    row = repo.get_label_info(label_id)
    if row is None:
        return 404, {"error_code": "not_found", "message": "label info not found"}
    return 200, row


def handle_get_label_user(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    repo = _build_repository()
    row = repo.get_label_info_for_user(label_id)
    if row is None:
        return 404, {"error_code": "label_not_found", "message": "label info not available"}
    return 200, row


def handle_get_backlog(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    style = (qs.get("style") or "").strip() or None
    status = (qs.get("status") or "").strip() or None
    if status and status not in ("none", "failed", "outdated"):
        raise ValidationError("status must be one of: none, failed, outdated")
    cursor = (qs.get("cursor") or "").strip() or None
    try:
        limit = int(qs.get("limit") or "100")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    repo = _build_repository()
    items, next_cursor, total = repo.list_backlog(
        style=style, status=status, cursor=cursor, limit=limit,
    )
    return 200, {"items": items, "next_cursor": next_cursor, "total_estimate": total}


def handle_get_options(event: Mapping[str, Any]) -> tuple[int, dict]:
    """Static config for the admin enqueue form."""
    del event  # unused — payload is static config
    from .prompts import list_prompt_versions, load_builtin_prompts

    load_builtin_prompts()
    prompt_versions = list_prompt_versions()
    return 200, {
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "prompt_versions": prompt_versions,
        "default_models": {
            "gemini": "gemini-2.5-pro",
            "openai": "gpt-5",
            "tavily_deepseek": "deepseek-chat",
        },
        "merge": {"vendor": "deepseek", "default_model": "deepseek-chat"},
    }


def handle_get_runs_list(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    status = (qs.get("status") or "").strip() or None
    if status and status not in ("queued", "running", "completed", "failed"):
        raise ValidationError("invalid status filter")
    cursor = (qs.get("cursor") or "").strip() or None
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    repo = _build_repository()
    items, next_cursor = repo.list_runs(status=status, cursor=cursor, limit=limit)
    return 200, {"items": items, "next_cursor": next_cursor}


def handle_get_labels_list(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    style = (qs.get("style") or "").strip() or None
    q = (qs.get("q") or "").strip() or None
    sort = (qs.get("sort") or "name").strip()
    if sort not in ("name", "recent"):
        raise ValidationError("sort must be 'name' or 'recent'")
    cursor = (qs.get("cursor") or "").strip() or None
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    repo = _build_repository()
    items, next_cursor = repo.list_labels(
        style=style, q=q, sort=sort, cursor=cursor, limit=limit,
    )
    return 200, {"items": items, "next_cursor": next_cursor}
