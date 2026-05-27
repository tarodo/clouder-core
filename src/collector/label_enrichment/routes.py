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
from .auto_repository import AutoEnrichRepository
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


def _build_auto_repository() -> AutoEnrichRepository:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return AutoEnrichRepository(data_api=client)


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


def handle_post_enrich_auto(event: Mapping[str, Any]) -> tuple[int, dict]:
    """Admin: enqueue one label using the registered auto-search settings."""
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")

    repo = _build_repository()
    row = repo.get_label_by_id(label_id)
    if row is None:
        return 404, {"error_code": "label_not_found", "message": "label not found"}

    cfg = _build_auto_repository().get_config("labels")
    if not cfg or not cfg.get("vendors") or not cfg.get("prompt_slug") \
            or not cfg.get("prompt_version") or not cfg.get("merge_vendor") \
            or not cfg.get("merge_model"):
        return 409, {
            "error_code": "auto_config_missing",
            "message": "auto-enrich config is not set up",
        }

    spec = RunSpec(
        prompt_slug=cfg["prompt_slug"],
        prompt_version=cfg["prompt_version"],
        vendors=list(cfg["vendors"]),
        models=dict(cfg.get("models") or {}),
        merge_vendor=cfg["merge_vendor"],
        merge_model=cfg["merge_model"],
        requested_labels=1,
        created_by_user_id=_extract_user_id(event),
    )
    run_id = repo.create_run(spec)

    style = repo.derive_style_for_label(label_id) or "music"
    sqs = _build_sqs_client()
    sqs.send_message(
        QueueUrl=_queue_url(),
        MessageBody=json.dumps({
            "run_id": run_id,
            "label_id": label_id,
            "label_name": row["name"],
            "style": style,
        }),
    )
    return 202, {"run_id": run_id, "queued_labels": 1}


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


def handle_get_label_history(event: Mapping[str, Any]) -> tuple[int, dict]:
    """All enrichment cells for one label across every run it appeared in."""
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    repo = _build_repository()
    items = repo.list_history_for_label(label_id)
    return 200, {"items": items}


def handle_get_label_user(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    repo = _build_repository()
    row = repo.get_label_info_for_user(label_id, user_id=_extract_user_id(event))
    if row is None:
        return 404, {"error_code": "label_not_found", "message": "label not found"}
    return 200, row


_BACKLOG_STATUSES = (
    "all",
    "none",
    "completed",
    "outdated",
)


def handle_get_backlog(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    style = (qs.get("style") or "").strip() or None
    status = (qs.get("status") or "").strip() or None
    if status and status not in _BACKLOG_STATUSES:
        raise ValidationError(
            "status must be one of: " + ", ".join(_BACKLOG_STATUSES)
        )
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


def handle_put_label_preference(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    user_id = _extract_user_id(event)
    if not user_id:
        raise ValidationError("user_id is required")

    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")
    status = body.get("status")
    if status not in ("liked", "disliked", "none"):
        raise ValidationError("status must be one of: liked, disliked, none")

    repo = _build_repository()
    if repo.get_label_by_id(label_id) is None:
        return 404, {"error_code": "label_not_found", "message": "label not found"}

    if status == "none":
        repo.delete_user_label_pref(user_id=user_id, label_id=label_id)
    else:
        repo.upsert_user_label_pref(
            user_id=user_id, label_id=label_id, status=status,
        )
    return 204, {}


def handle_get_my_label_preferences(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    status = (qs.get("status") or "liked").strip()
    if status not in ("liked", "disliked"):
        raise ValidationError("status must be 'liked' or 'disliked'")
    try:
        page = int(qs.get("page") or "1")
    except (TypeError, ValueError):
        raise ValidationError("page must be an integer")
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if page < 1:
        raise ValidationError("page must be >= 1")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    user_id = _extract_user_id(event)
    if not user_id:
        raise ValidationError("user_id is required")
    repo = _build_repository()
    items, total = repo.list_user_label_prefs(
        user_id=user_id, status=status, page=page, limit=limit,
    )
    return 200, {"items": items, "total": total, "page": page, "limit": limit}


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
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "merge": {"vendor": "deepseek", "default_model": "deepseek-v4-flash"},
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
    source = (qs.get("source") or "").strip() or None
    if source and source not in ("manual", "auto"):
        raise ValidationError("source must be 'manual' or 'auto'")
    repo = _build_repository()
    items, next_cursor = repo.list_runs(status=status, cursor=cursor, limit=limit, source=source)
    return 200, {"items": items, "next_cursor": next_cursor}


def handle_get_labels_list(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    style = (qs.get("style") or "").strip() or None
    q = (qs.get("q") or "").strip() or None
    sort = (qs.get("sort") or "name").strip()
    if sort not in ("name", "recent"):
        raise ValidationError("sort must be 'name' or 'recent'")
    my = (qs.get("my") or "all").strip()
    if my not in ("all", "liked", "disliked", "unrated"):
        raise ValidationError("my must be one of: all, liked, disliked, unrated")
    try:
        page = int(qs.get("page") or "1")
    except (TypeError, ValueError):
        raise ValidationError("page must be an integer")
    if page < 1:
        raise ValidationError("page must be >= 1")
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    repo = _build_repository()
    user_id = _extract_user_id(event)
    items, total = repo.list_labels(
        style=style, q=q, sort=sort, page=page, limit=limit,
        user_id=user_id, my=my,
    )
    return 200, {"items": items, "total": total, "page": page, "limit": limit}
