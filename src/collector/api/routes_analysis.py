"""Audio analysis: the external analyzer's claim/results (service token) and the admin view."""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .. import audio_profile, ml_jobs
from ..errors import AppError, ValidationError
from ..schemas import (
    AnalysisClaimRequest,
    AnalysisFeaturesRequest,
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
        limit=request.limit,
        analyzers=request.analyzers,
        lease_id=lease_id,
        now=now,
        lease_seconds=request.lease_seconds,
    )
    return _json_response(
        200,
        {
            "lease_id": lease_id,
            "lease_expires_at": (now + timedelta(seconds=request.lease_seconds)).isoformat(),
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


def _build_s3_client():
    import boto3

    return boto3.client("s3")


def _features_bucket() -> str:
    bucket = os.environ.get("AUDIO_FEATURES_BUCKET", "").strip()
    if not bucket:
        raise AppError(
            status_code=503,
            error_code="features_not_configured",
            message="Feature store is not configured",
        )
    return bucket


def _handle_analysis_features(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    _require_service(event)
    request = _parse(event, AnalysisFeaturesRequest)
    vectors: dict[str, bytes] = {}
    rejected = []
    for item in request.items:
        try:
            data = base64.b64decode(item.vector_b64, validate=True)
            audio_profile.decode_vector(data)
        except ValueError:  # binascii.Error included
            rejected.append({"video_id": item.video_id, "reason": "bad_vector"})
            continue
        vectors[item.video_id] = data
    accepted = [i for i in request.items if i.video_id in vectors]
    if accepted:
        repository = _repository()
        known = repository.known_audio_features(video_ids=list(vectors))
        # The object goes first: a row never points at a profile S3 does not hold.
        # An S3 error fails the request and the analyzer retries the batch.
        changed = [i for i in accepted if known.get(i.video_id) != (i.version, i.audio_sha256)]
        if changed:
            s3, bucket = _build_s3_client(), _features_bucket()
            for item in changed:
                s3.put_object(
                    Bucket=bucket,
                    Key=audio_profile.s3_key(item.video_id),
                    Body=vectors[item.video_id],
                )
        repository.record_audio_features(
            items=[i.model_dump(include={"video_id", "version", "audio_sha256"}) for i in accepted],
            now=deps.utc_now(),
        )
        ml_jobs.enqueue_score(video_ids=[i.video_id for i in accepted])
    return _json_response(200, {"accepted": len(accepted), "rejected": rejected}, correlation_id)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _handle_analysis_status(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    repository, now = _repository(), deps.utc_now()
    status = repository.analysis_status(now=now)
    items = repository.ml_models_overview(now=now)
    return _json_response(
        200,
        {
            **status,
            "last_claim_at": _iso(status["last_claim_at"]),
            "last_result_at": _iso(status["last_result_at"]),
            "analyzers": [
                {**a, "last_result_at": _iso(a["last_result_at"])} for a in status["analyzers"]
            ],
            "models": {
                **status["models"],
                "last_trained_at": _iso(status["models"]["last_trained_at"]),
                "items": [{**i, "trained_at": _iso(i["trained_at"])} for i in items],
            },
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
