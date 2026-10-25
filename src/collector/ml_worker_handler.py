"""SQS worker (ml-jobs queue): retrain a user's model of a style and score tracks (spec §5).

Messages, by `type`:
- `retrain` {user_id, style_id}: labels -> profiles -> train -> artifact -> ml_models, then scoring;
- `score_style` {user_id, style_id, model_version, after_track_id}: one page of the style's profiled
  tracks, then the next page as a new message, until the model row moves past model_version;
- `score` {video_ids}: freshly profiled videos, by every trained model of their tracks' styles.
A bad record raises, so SQS redrives it to the DLQ. Needs numpy and scikit-learn (the ML package).
"""

from __future__ import annotations

import json
import os
import resource
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Any

import numpy as np

from . import ml_jobs
from .logging_utils import log_event
from .ml.features import s3_fetcher, vectors
from .ml.labels import Label, training_rows
from .ml.model import Model, Prediction, evaluate_previous, from_npz, predict, to_npz, train
from .repositories import ClouderRepository, create_clouder_repository_from_env, utc_now

PAGE = 2000  # tracks per scoring message: ~67 MB of profiles

# ponytail: unbounded, one entry per (user, style, version) a container has scored; a small circle of
# users. An LRU if containers ever hold many.
_MODELS: dict[str, Model] = {}


def _build_s3_client() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client("s3", config=Config(max_pool_connections=32))


def _model(s3: Any, bucket: str, key: str) -> Model:
    if key not in _MODELS:
        _MODELS[key] = from_npz(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    return _MODELS[key]


def _labels(repo: ClouderRepository, user_id: str, style_id: str) -> list[Label]:
    labels: list[Label] = []
    after = None
    while True:
        rows = repo.ml_labels(user_id=user_id, style_id=style_id, after_track_id=after, limit=PAGE)
        labels += [Label(**r) for r in rows]
        if len(rows) < PAGE:
            return labels
        after = rows[-1]["track_id"]


def _stored(row: Mapping[str, Any]) -> Prediction:
    categories = row["categories"]
    return Prediction(
        row["keep_score"],
        row["keep"],
        None if categories is None else [(c, p) for c, p in categories],
    )


def _metrics(
    repo: ClouderRepository,
    user_id: str,
    style_id: str,
    version: int,
    trained_at: datetime | None,
    labels: list[Label],
) -> dict[str, Any]:
    """The previous model's (version's) stored predictions against the labels added since it trained.
    Only its own rows: a scoring chain that died partway leaves an older version's rows behind."""
    since = [x for x in labels if trained_at is not None and x.added_at > trained_at]
    stored = (
        repo.ml_predictions(
            user_id=user_id, style_id=style_id, track_ids=[x.track_id for x in since]
        )
        if since
        else {}
    )
    known = [x for x in since if stored.get(x.track_id, {}).get("model_version") == version]
    alive = set(repo.ml_alive_categories(user_id=user_id, style_id=style_id)) if known else set()
    return evaluate_previous([_stored(stored[x.track_id]) for x in known], known, alive)


def _retrain(repo: ClouderRepository, s3: Any, bucket: str, msg: Mapping[str, Any]) -> None:
    started = time.monotonic()
    user_id, style_id = msg["user_id"], msg["style_id"]
    previous = repo.ml_model(user_id=user_id, style_id=style_id)
    version = previous["version"] if previous else 0
    now = utc_now()  # the labels' snapshot: later placements count toward the next retrain
    labels = _labels(repo, user_id, style_id)
    video_ids, keep, category = training_rows(labels)
    present, X = vectors(video_ids, s3_fetcher(s3, bucket))
    profiled = set(present)
    rows = [i for i, v in enumerate(video_ids) if v in profiled]  # in `present` order
    model = train(X, keep[rows], [category[i] for i in rows])
    if model is None:
        # Never trained: restart the 150-label count at the snapshot. A model exists: leave the
        # request pending (an hour), so later taps do not re-enqueue a retrain that cannot train.
        if version == 0:
            repo.ml_mark_too_few_labels(user_id=user_id, style_id=style_id, now=now)
        log_event(
            "INFO", "ml_retrain_too_few_labels", user_id=user_id, style_id=style_id, count=len(rows)
        )
        return
    # Version 0 has no model, so no predictions to score (its trained_at only restarts the count).
    trained_at = previous["trained_at"] if previous and version > 0 else None
    # The container's peak so far (ru_maxrss is KB on Linux), against the 3008 MB cap.
    max_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    metrics = {
        **_metrics(repo, user_id, style_id, version, trained_at, labels),
        "cv": model.cv,
        "rows_total": len(rows),  # n_labels counts the keep head's rows (MAX_TRAIN_ROWS)
        "max_rss_mb": max_rss_mb,
    }
    # A per-attempt key: a duplicate retrain of the pair racing this one writes its own file, so the
    # row the save below keeps always names its own model.
    # ponytail: the losing attempt's file stays in S3 as an orphan (~1 MB); a cleanup if races recur.
    key = f"models/{user_id}/{style_id}/v{version + 1}-{uuid.uuid4().hex[:12]}.npz"
    s3.put_object(Bucket=bucket, Key=key, Body=to_npz(model))
    saved = repo.ml_save_model(
        user_id=user_id,
        style_id=style_id,
        expected_version=version,
        n_labels=model.n_labels,
        n_keep=model.n_keep,
        keep_threshold=model.keep_threshold,
        classes=list(model.category.classes) if model.category else None,
        metrics=metrics,
        artifact_key=key,
        now=now,
    )
    log_event(
        "INFO",
        "ml_retrain_saved" if saved else "ml_retrain_superseded",
        user_id=user_id,
        style_id=style_id,
        model_version=version + 1,
        count=model.n_labels,
        duration_ms=int((time.monotonic() - started) * 1000),
        max_rss_mb=max_rss_mb,
    )
    if saved:
        ml_jobs.enqueue_score_style(
            user_id=user_id, style_id=style_id, model_version=version + 1, after_track_id=None
        )


def _upsert(
    repo: ClouderRepository,
    model: Model,
    user_id: str,
    style_id: str,
    version: int,
    tracks: list[dict[str, Any]],
    present: list[str],
    X: np.ndarray,
) -> None:
    """Predict the profiled videos once, then store a row per track on them."""
    by_video = dict(zip(present, predict(model, X), strict=True))
    rows = [
        {"track_id": t["track_id"], **asdict(by_video[t["video_id"]])}
        for t in tracks
        if t["video_id"] in by_video
    ]
    if rows:
        repo.ml_upsert_predictions(
            user_id=user_id, style_id=style_id, model_version=version, rows=rows, now=utc_now()
        )


def _profiles(s3: Any, bucket: str, tracks: list[dict[str, Any]]) -> tuple[list[str], np.ndarray]:
    return vectors(list(dict.fromkeys(t["video_id"] for t in tracks)), s3_fetcher(s3, bucket))


def _score_style(repo: ClouderRepository, s3: Any, bucket: str, msg: Mapping[str, Any]) -> None:
    user_id, style_id, version = msg["user_id"], msg["style_id"], msg["model_version"]
    row = repo.ml_model(user_id=user_id, style_id=style_id)
    if row is None or row["version"] != version:
        return  # retrained since: the newer version scores the style
    tracks = repo.ml_style_tracks(
        style_id=style_id, after_track_id=msg["after_track_id"], limit=PAGE
    )
    model = _model(s3, bucket, row["artifact_key"])
    _upsert(repo, model, user_id, style_id, version, tracks, *_profiles(s3, bucket, tracks))
    if len(tracks) == PAGE:
        ml_jobs.enqueue_score_style(
            user_id=user_id,
            style_id=style_id,
            model_version=version,
            after_track_id=tracks[-1]["track_id"],
        )


def _score(repo: ClouderRepository, s3: Any, bucket: str, msg: Mapping[str, Any]) -> None:
    tracks = repo.ml_tracks_for_videos(video_ids=msg["video_ids"])
    present, X = _profiles(s3, bucket, tracks)
    styles: dict[str, list[dict[str, Any]]] = {}
    for t in tracks:
        styles.setdefault(t["style_id"], []).append(t)
    for style_id, rows in styles.items():
        for m in repo.ml_models_for_style(style_id=style_id):
            model = _model(s3, bucket, m["artifact_key"])
            _upsert(repo, model, m["user_id"], style_id, m["version"], rows, present, X)


_JOBS: dict[str, Callable[[ClouderRepository, Any, str, Mapping[str, Any]], None]] = {
    "retrain": _retrain,
    "score_style": _score_style,
    "score": _score,
}


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    repo = create_clouder_repository_from_env()
    if repo is None:
        raise RuntimeError("AURORA Data API configuration is required for the ML worker")
    s3 = _build_s3_client()
    bucket = os.environ["AUDIO_FEATURES_BUCKET"]
    records = event.get("Records", [])
    for record in records:
        msg = json.loads(record["body"])
        _JOBS[msg["type"]](repo, s3, bucket, msg)
    return {"processed": len(records)}
