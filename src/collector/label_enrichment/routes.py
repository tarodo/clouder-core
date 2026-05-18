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
from .messages import EnrichLabelsRequestIn
from .repository import LabelEnrichmentRepository, RunSpec


def _build_repository() -> LabelEnrichmentRepository:
    client = create_default_data_api_client()
    if client is None:
        raise RuntimeError("Aurora Data API not configured")
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

    repo = _build_repository()
    sqs = _build_sqs_client()
    queue_url = _queue_url()

    label_ids: list[tuple[str, str, str, str | None]] = []
    for item in req.labels:
        lid = repo.upsert_label_by_name(item.label_name)
        label_ids.append((lid, item.label_name, item.style, item.release_name))

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

    for lid, name, style, release in label_ids:
        msg = {
            "run_id": run_id,
            "label_id": lid,
            "label_name": name,
            "style": style,
            "release_name": release,
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
