"""ML worker: retrain a user's style model and score tracks, with fakes for the repo, S3 and SQS."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from collector import audio_profile
from collector import ml_worker_handler as worker
from collector.logging_utils import ALLOWED_LOG_FIELDS
from collector.ml import model as ml

T = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 23, tzinfo=UTC)
U, S = "u1", "st"
BUCKET = "features"


class NoSuchKey(Exception):
    pass


class FakeS3:
    class exceptions:  # boto3 names it so
        NoSuchKey = NoSuchKey

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.gets: list[str] = []

    def get_object(self, *, Bucket, Key):
        assert Bucket == BUCKET
        self.gets.append(Key)
        if Key not in self.objects:
            raise NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body):
        assert Bucket == BUCKET
        self.objects[Key] = Body


class FakeSQS:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.fail = False

    def send_message(self, *, QueueUrl, MessageBody):
        assert QueueUrl == "https://sqs/ml-jobs"
        if self.fail:
            raise RuntimeError("sqs down")
        self.messages.append(json.loads(MessageBody))


CLOCK: list[datetime] = []  # every utc_now() reading of the worker


def _now() -> datetime:
    CLOCK.append(NOW)
    return NOW


class FakeRepo:
    def __init__(self, *, model=None, labels=(), tracks=(), models=None, predictions=None):
        self.model = model  # the ml_models row of (U, S)
        self.labels = sorted(labels, key=lambda r: r["track_id"])
        self.tracks = list(tracks)  # {track_id, video_id, style_id}
        self.models = models or {}  # style_id -> ml_models_for_style rows
        self.predictions = predictions or {}
        self.save_ok = True
        self.saved: list[dict] = []
        self.marked: list[tuple[str, str, datetime]] = []
        self.clock_at_labels: int | None = None
        self.upserts: list[tuple[str, str, int, list[dict]]] = []

    def ml_model(self, *, user_id, style_id):
        return self.model

    def ml_labels(self, *, user_id, style_id, after_track_id=None, limit=2000):
        if self.clock_at_labels is None:
            self.clock_at_labels = len(CLOCK)
        return [r for r in self.labels if r["track_id"] > (after_track_id or "")][:limit]

    def ml_predictions(self, *, user_id, style_id, track_ids):
        return {t: self.predictions[t] for t in track_ids if t in self.predictions}

    def ml_alive_categories(self, *, user_id, style_id):
        return ["ca", "cb"]

    def ml_save_model(self, **kw):
        self.saved.append(kw)
        return self.save_ok

    def ml_mark_too_few_labels(self, *, user_id, style_id, now):
        self.marked.append((user_id, style_id, now))

    def ml_style_tracks(self, *, style_id, after_track_id=None, limit=2000):
        rows = [t for t in self.tracks if t["style_id"] == style_id]
        return [
            {"track_id": t["track_id"], "video_id": t["video_id"]}
            for t in rows
            if t["track_id"] > (after_track_id or "")
        ][:limit]

    def ml_tracks_for_videos(self, *, video_ids):
        return [t for t in self.tracks if t["video_id"] in video_ids]

    def ml_models_for_style(self, *, style_id):
        return self.models.get(style_id, [])

    def ml_upsert_predictions(self, *, user_id, style_id, model_version, rows, now):
        assert now == NOW
        self.upserts.append((user_id, style_id, model_version, rows))
        return len(rows)


def _blob(x: np.ndarray) -> bytes:
    return x.astype("<f2").tobytes()


def _vector(**dims: float) -> np.ndarray:
    x = np.zeros(audio_profile.DIMS, dtype=np.float32)
    for i, v in dims.items():
        x[int(i[1:])] = v
    return x


def _features(vectors: dict[str, np.ndarray]) -> dict[str, bytes]:
    return {audio_profile.s3_key(v): _blob(x) for v, x in vectors.items()}


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setenv("AUDIO_FEATURES_BUCKET", BUCKET)
    monkeypatch.setenv("ML_JOBS_QUEUE_URL", "https://sqs/ml-jobs")
    monkeypatch.setattr(worker, "_MODELS", {})
    CLOCK.clear()
    monkeypatch.setattr(worker, "utc_now", _now)
    sqs = FakeSQS()
    monkeypatch.setattr("collector.ml_jobs._build_sqs_client", lambda: sqs)

    def _run(repo: FakeRepo, s3: FakeS3, *messages: dict) -> FakeSQS:
        monkeypatch.setattr(worker, "create_clouder_repository_from_env", lambda: repo)
        monkeypatch.setattr(worker, "_build_s3_client", lambda: s3)
        records = [{"body": json.dumps(m)} for m in messages]
        assert worker.lambda_handler({"Records": records}, None) == {"processed": len(records)}
        return sqs

    _run.sqs = sqs  # type: ignore[attr-defined]
    return _run


def _label(track_id: str, keep: bool, category: str | None, added_at: datetime = T) -> dict:
    return {
        "track_id": track_id,
        "video_id": f"v_{track_id}",
        "keep": keep,
        "category_id": category,
        "added_at": added_at,
    }


def _world(n_each: int = 35) -> tuple[list[dict], dict[str, bytes]]:
    """2 * n_each discards (d*) and n_each keeps in ca and cb each (k*), with a learnable profile;
    plus one keep whose profile is missing from S3."""
    rng = np.random.default_rng(0)
    labels = [_label(f"d{i:03}", False, None) for i in range(2 * n_each)]
    labels += [_label(f"k{i:03}", True, "ca" if i < n_each else "cb") for i in range(2 * n_each)]
    vectors = {}
    for r in labels:
        x = _vector()
        x[:8] = rng.normal(size=8)
        x[0] += 3 * r["keep"]
        x[1] += 3 * (r["category_id"] == "ca") - 3 * (r["category_id"] == "cb")
        vectors[r["video_id"]] = x
    return [*labels, _label("m000", True, "ca")], _features(vectors)


RETRAIN = {"type": "retrain", "user_id": U, "style_id": S}
NO_METRICS = {
    "first_hit": None,
    "first_n": 0,
    "keep_auc": None,
    "keep_n": 0,
    "top1": None,
    "top2": None,
    "cat_n": 0,
}


@pytest.mark.parametrize("version", [None, 0, 2])
def test_retrain_too_few_labels_writes_nothing(run, version: int | None) -> None:
    """Never trained: the label count restarts at the snapshot. A model exists: the request stays
    pending (an hour), so taps do not re-enqueue a retrain that cannot train."""
    labels, features = _world(n_each=5)
    model = None if version is None else {"version": version, "trained_at": None}
    repo, s3 = FakeRepo(model=model, labels=labels), FakeS3(features)
    sqs = run(repo, s3, RETRAIN)
    assert repo.saved == [] and sqs.messages == []
    assert repo.marked == ([] if version else [(U, S, NOW)])
    assert repo.clock_at_labels == 1  # the snapshot time is read before the labels
    assert not any(k.startswith("models/") for k in s3.objects)


def _pred(keep_score: float, ca: float) -> dict:
    return {
        "model_version": 2,
        "keep_score": keep_score,
        "keep": keep_score >= 0.5,
        "categories": sorted([["ca", ca], ["cb", 1 - ca]], key=lambda c: -c[1]),
    }


@pytest.mark.parametrize("previous", [False, True])
def test_retrain_saves_artifact_and_enqueues_scoring(run, previous: bool) -> None:
    labels, features = _world()
    repo = FakeRepo(labels=labels)
    metrics = NO_METRICS
    if previous:
        trained_at = T + timedelta(days=1)
        repo.model = {"version": 2, "trained_at": trained_at, "retrain_requested_at": trained_at}
        later = trained_at + timedelta(hours=1)
        for r in labels:
            if r["track_id"] in ("d000", "d001", "k000", "k035"):
                r["added_at"] = later
        repo.predictions = {  # d001's row is from v1 (a scoring chain that died): it does not count
            "d000": _pred(0.25, 0.5),  # DISCARD lit: hit
            "d001": {**_pred(0.75, 0.5), "model_version": 1},  # would count as a miss
            "k000": _pred(0.75, 0.875),  # ca lit: hit
            "k035": _pred(0.625, 0.625),  # ca lit for a cb keep: miss, top-2 hit
        }
        metrics = {
            "first_hit": 2 / 3,
            "first_n": 3,
            "keep_auc": 1.0,
            "keep_n": 3,
            "top1": 0.5,
            "top2": 1.0,
            "cat_n": 2,
        }
    s3 = FakeS3(features)
    sqs = run(repo, s3, RETRAIN)
    version = 3 if previous else 1
    (saved,) = repo.saved
    key = saved["artifact_key"]
    assert re.fullmatch(rf"models/{U}/{S}/v{version}-[0-9a-f]{{12}}\.npz", key)
    assert repo.clock_at_labels == 1  # trained_at is the labels' snapshot time
    stored = saved.pop("metrics")
    assert set(stored.pop("cv")) == {"keep_auc", "category_bacc"}
    assert stored.pop("rows_total") == 140
    assert stored.pop("max_rss_mb") > 0
    assert stored == metrics
    threshold = saved.pop("keep_threshold")
    assert 0 < threshold < 1
    assert saved == {
        "user_id": U,
        "style_id": S,
        "expected_version": version - 1,
        "n_labels": 140,  # the keep without a profile is not a row
        "n_keep": 70,
        "classes": ["ca", "cb"],
        "artifact_key": key,
        "now": NOW,
    }
    model = ml.from_npz(s3.objects[key])
    assert (model.keep_threshold, model.n_labels) == (threshold, 140)
    assert [k for k in s3.objects if k.startswith("models/")] == [key]
    assert sqs.messages == [
        {
            "type": "score_style",
            "user_id": U,
            "style_id": S,
            "model_version": version,
            "after_track_id": None,
        }
    ]


def test_retrain_caps_rows_and_logs_peak_memory(run, monkeypatch) -> None:
    """Over MAX_TRAIN_ROWS the keep head trains on the newest rows; the metrics keep the full count."""
    monkeypatch.setattr(ml, "MAX_TRAIN_ROWS", 130)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(worker, "log_event", lambda level, msg, **kw: events.append((msg, kw)))
    labels, features = _world()
    repo = FakeRepo(labels=labels)
    run(repo, FakeS3(features), RETRAIN)
    (saved,) = repo.saved
    assert (saved["n_labels"], saved["n_keep"], saved["metrics"]["rows_total"]) == (130, 70, 140)
    ((_, logged),) = [e for e in events if e[0] == "ml_retrain_saved"]
    assert logged["max_rss_mb"] > 0 and "max_rss_mb" in ALLOWED_LOG_FIELDS
    assert saved["metrics"]["max_rss_mb"] == logged["max_rss_mb"]  # the admin table shows it


def test_retrain_superseded_save_enqueues_nothing(run) -> None:
    """Another retrain of the pair saved first: its scoring runs; this attempt's file is an orphan."""
    labels, features = _world()
    repo, s3 = FakeRepo(labels=labels), FakeS3(features)
    repo.save_ok = False
    sqs = run(repo, s3, RETRAIN)
    assert len(repo.saved) == 1 and sqs.messages == []
    assert repo.marked == [] and repo.upserts == []
    assert [k for k in s3.objects if k.startswith("models/")] == [repo.saved[0]["artifact_key"]]


def test_retrain_enqueue_failure_raises(run) -> None:
    labels, features = _world()
    run.sqs.fail = True
    with pytest.raises(RuntimeError, match="sqs down"):  # SQS redrives the retrain
        run(FakeRepo(labels=labels), FakeS3(features), RETRAIN)


def _tiny_model() -> ml.Model:
    """P(keep) = sigmoid(x0), threshold 0.5; categories softmax([0, x1]) over (ca, cb)."""
    d = audio_profile.DIMS
    w_keep, w_cat = np.zeros((d, 1), np.float32), np.zeros((d, 2), np.float32)
    w_keep[0, 0] = w_cat[1, 1] = 1
    zeros = np.zeros(d, np.float32)
    keep = ml.Head(zeros, w_keep, np.zeros(1, np.float32), ("keep",))
    category = ml.Head(zeros, w_cat, np.zeros(2, np.float32), ("ca", "cb"))
    return ml.Model(keep, 0.5, category, 140, 70, {})


def _track(track_id: str, style: str = S) -> dict:
    return {"track_id": track_id, "video_id": f"v_{track_id}", "style_id": style}


def _style_world() -> tuple[FakeRepo, FakeS3, dict]:
    """Model v1 of (U, S); the style has t1, t2 and t3 (no profile); t4 is another style."""
    key = f"models/{U}/{S}/v1.npz"
    features = _features({"v_t1": _vector(x0=2, x1=-1), "v_t2": _vector(x0=-2, x1=1)})
    s3 = FakeS3({key: ml.to_npz(_tiny_model()), **features})
    tracks = [_track("t1"), _track("t2"), _track("t3"), _track("t4", "st2")]
    repo = FakeRepo(model={"version": 1, "artifact_key": key}, tracks=tracks)
    first = {
        "type": "score_style",
        "user_id": U,
        "style_id": S,
        "model_version": 1,
        "after_track_id": None,
    }
    return repo, s3, first


def test_score_style_pages_and_stops_on_newer_version(run, monkeypatch) -> None:
    monkeypatch.setattr(worker, "PAGE", 2)
    repo, s3, first = _style_world()
    sqs = run(repo, s3, first)
    (page,) = repo.upserts
    assert page[:3] == (U, S, 1)
    t1, t2 = page[3]
    assert (t1["track_id"], t1["keep"], t1["categories"][0][0]) == ("t1", True, "ca")
    assert (t2["track_id"], t2["keep"], t2["categories"][0][0]) == ("t2", False, "cb")
    assert t1["keep_score"] == pytest.approx(1 / (1 + np.exp(-2)), abs=1e-3)
    assert sqs.messages == [first | {"after_track_id": "t2"}]

    run(repo, s3, sqs.messages.pop())
    scored = [r["track_id"] for *_, rows in repo.upserts for r in rows]
    assert scored == ["t1", "t2"]  # t3 has no profile, t4 is another style
    assert sqs.messages == []  # a short page ends the chain

    repo.model = {"version": 2, "artifact_key": f"models/{U}/{S}/v2.npz"}  # retrained meanwhile
    run(repo, s3, first)
    assert [r["track_id"] for *_, rows in repo.upserts for r in rows] == scored
    assert sqs.messages == []


def test_score_style_next_page_send_failure_raises(run, monkeypatch) -> None:
    """The chain must not end silently: the record fails, SQS redrives it, the page is re-scored."""
    monkeypatch.setattr(worker, "PAGE", 2)
    repo, s3, first = _style_world()
    run.sqs.fail = True
    with pytest.raises(RuntimeError, match="sqs down"):
        run(repo, s3, first)
    run.sqs.fail = False
    run(repo, s3, first)  # the redrive
    assert len(repo.upserts) == 2 and repo.upserts[0] == repo.upserts[1]  # same version: rewrite
    assert run.sqs.messages == [first | {"after_track_id": "t2"}]


def test_score_style_without_queue_url_raises(run, monkeypatch) -> None:
    monkeypatch.setattr(worker, "PAGE", 2)
    monkeypatch.delenv("ML_JOBS_QUEUE_URL")
    repo, s3, first = _style_world()
    with pytest.raises(RuntimeError, match="ML_JOBS_QUEUE_URL"):
        run(repo, s3, first)


def test_score_new_videos_uses_style_models(run) -> None:
    k1, k2 = f"models/{U}/{S}/v1.npz", f"models/u2/{S}/v3.npz"
    s3 = FakeS3(
        {
            k1: ml.to_npz(_tiny_model()),
            k2: ml.to_npz(_tiny_model()),
            **_features({"v_t1": _vector(x0=2), "v_t9": _vector()}),
        }
    )
    repo = FakeRepo(
        tracks=[_track("t1"), _track("t2"), _track("t9", "st2")],  # t2: no profile
        models={
            S: [
                {"user_id": U, "version": 1, "artifact_key": k1},
                {"user_id": "u2", "version": 3, "artifact_key": k2},
            ]
        },
    )
    message = {"type": "score", "video_ids": ["v_t1", "v_t2", "v_t9"]}
    run(repo, s3, message, message)
    assert [(u, s, v, [r["track_id"] for r in rows]) for u, s, v, rows in repo.upserts] == [
        (U, S, 1, ["t1"]),
        ("u2", S, 3, ["t1"]),
    ] * 2
    assert [k for k in s3.gets if k.startswith("models/")] == [k1, k2]  # cached per container


def test_bad_record_raises(run) -> None:
    with pytest.raises(KeyError):
        run(FakeRepo(), FakeS3({}), {"type": "nope"})
