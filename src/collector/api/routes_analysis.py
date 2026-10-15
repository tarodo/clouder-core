"""Audio analysis: the external analyzer's claim/results (service token) and the admin view."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ..errors import AppError, ValidationError
from ..repositories.analysis import LEASE_SECONDS
from ..schemas import (
    AnalysisClaimRequest,
    AnalysisRequeueRequest,
    AnalysisResultsRequest,
    validation_error_message,
)
from . import deps
from .http import _json_response, _parse_json_body, _require_service


def _parse[M: BaseModel](event: Mapping[str, Any], model: type[M]) -> M:
    try:
        return model.model_validate(_parse_json_body(event))
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc)) from exc


def _repository() -> Any:
    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        raise AppError(
            status_code=503, error_code="db_not_configured", message="Database is not configured"
        )
    return repository


def _handle_analysis_claim(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    _require_service(event)
    request = _parse(event, AnalysisClaimRequest)
    now, lease_id = deps.utc_now(), str(uuid4())
    tracks = _repository().claim_analysis(
        limit=request.limit, analyzers=request.analyzers, lease_id=lease_id, now=now
    )
    return _json_response(
        200,
        {
            "lease_id": lease_id,
            "lease_expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
            "tracks": tracks,
        },
        correlation_id,
    )


def _handle_analysis_results(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    _require_service(event)
    request = _parse(event, AnalysisResultsRequest)
    items = [item.model_dump(mode="json") for item in request.results]
    rejected = _repository().record_analysis_results(
        lease_id=str(request.lease_id), items=items, now=deps.utc_now()
    )
    return _json_response(
        200, {"accepted": len(items) - len(rejected), "rejected": rejected}, correlation_id
    )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _handle_analysis_status(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    status = _repository().analysis_status(now=deps.utc_now())
    return _json_response(
        200,
        {
            **status,
            "last_claim_at": _iso(status["last_claim_at"]),
            "last_result_at": _iso(status["last_result_at"]),
        },
        correlation_id,
    )


def _handle_analysis_requeue(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    request = _parse(event, AnalysisRequeueRequest)
    requeued = _repository().requeue_analysis(
        analyzer=request.analyzer,
        scope=request.scope,
        days=request.days,
        include_failed=request.include_failed,
        now=deps.utc_now(),
    )
    return _json_response(200, {"requeued": requeued}, correlation_id)
