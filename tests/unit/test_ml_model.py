from __future__ import annotations

import tracemalloc
from datetime import UTC, datetime

import numpy as np
import pytest

from collector.ml import model as ml
from collector.ml.labels import Label
from collector.ml.model import Head, Model, Prediction

BLOCKS = (("a", 0, 8), ("b", 8, 4))
D = 12
T = datetime(2026, 10, 1, tzinfo=UTC)


def _keep_data(n: int, n_keep: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    y = rng.permutation(np.arange(n) < n_keep)
    X = rng.normal(size=(n, D))
    X[:, 0] += 1.2 * y
    X[:, 9] += 0.8 * y
    return X.astype(np.float32), y


def _category_data(sizes: dict[str, int], seed: int) -> tuple[np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    y = [c for c, k in sizes.items() for _ in range(k)]
    X = rng.normal(size=(len(y), D))
    for j, c in enumerate(sizes):
        X[[i for i, v in enumerate(y) if v == c], j] += 2.0
    return X.astype(np.float32), y


def _awkward(X: np.ndarray) -> np.ndarray:
    X = X.copy()
    X[:, 5] = 3.0  # constant column
    X[::7, 2] = np.nan  # NaN in some rows
    return X


@pytest.mark.parametrize(
    ("task", "k", "n", "offset"),
    [
        ("keep", 2, 200, 0.0),
        ("keep", 2, 10, 0.0),
        ("category", 2, 200, 0.0),
        ("category", 3, 200, 0.0),
        ("keep", 2, 200, 1000.0),
        ("category", 3, 200, 1000.0),
    ],
)
def test_collapsed_head_matches_pipeline(task: str, k: int, n: int, offset: float) -> None:
    """n=10 < D: the PCA is a projection onto the train rows, not a full rotation (the production shape).
    offset: column means far from their spread; at 12 columns it takes ~1000 sd to lose the digits that ~30 sd
    loses at 16 778, when float32 sums raw X against a bias that cancels the means."""
    w = ml.block_weights(BLOCKS, D)
    if task == "keep":
        X, y = _keep_data(n, n * 2 // 5, seed=1)
        Xt, _ = _keep_data(100, 40, seed=2)
    else:
        sizes = {f"c{j}": n // k for j in range(k)}
        X, labels = _category_data(sizes, seed=1)
        Xt, _ = _category_data(sizes, seed=2)
        y = np.array(labels)
    X, Xt = _awkward(X + np.float32(offset)), _awkward(Xt + np.float32(offset))
    Xt[::5, 7] = np.nan  # a column with no NaN at fit time
    X0 = X.copy()
    pipe = ml.fit_pipeline(X, y, w, task)
    np.testing.assert_array_equal(X, X0)  # PCA(copy=False) centres a pipeline temporary, not X
    assert pipe[:-2].transform(X).dtype == np.float32  # the PCA input: float32 end to end
    head = ml.collapse(pipe)
    want = pipe.predict_proba(Xt)
    if task == "keep":
        assert head.classes == ("keep",)
        want = want[:, 1:]
    else:
        assert head.classes == tuple(pipe.classes_)
    got = head.proba(Xt)
    assert got.shape == want.shape
    assert np.abs(got - want).max() <= 1e-5


def test_training_peak_stays_under_four_matrices() -> None:
    """The 3008 MB Lambda: the keep head's numpy peak, beyond X itself, in copies of X (float32). ma.median's
    whole-matrix argsort took ~5.8, a float64 weighted matrix and its PCA copies ~8.4."""
    n, d = 400, 1500  # the production shape's d/n (16 778 / 4 500)
    rng = np.random.default_rng(0)
    X = rng.standard_normal((n, d), dtype=np.float32)
    X[::9, 3] = np.nan
    keep = rng.random(n) < 0.4
    tracemalloc.start()
    try:
        ml.train(X, keep, [None] * n, blocks=(("a", 0, d),))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak / X.nbytes < 4


def test_train_none_below_thresholds() -> None:
    X, keep = _keep_data(100, 50, seed=0)
    assert ml.train(X, keep, [None] * 100, blocks=BLOCKS) is None
    keep = np.arange(100) < 58
    category = ["a"] * 29 + ["b"] * 29 + [None] * 42
    assert ml.train(X, keep, category, blocks=BLOCKS) is None


@pytest.mark.parametrize(
    ("n", "n_keep", "trains"),
    [(130, 35, True), (129, 35, False), (130, 34, False), (130, 95, True), (130, 96, False)],
)
def test_keep_head_thresholds(n: int, n_keep: int, trains: bool) -> None:
    X, keep = _keep_data(n, n_keep, seed=4)
    m = ml.train(X, keep, [None] * n, blocks=BLOCKS)
    assert (m is not None and m.keep is not None) == trains


def test_keep_head_int_labels_match_bool() -> None:
    X, keep = _keep_data(140, 50, seed=3)
    a = ml.train(X, keep, [None] * 140, blocks=BLOCKS)
    b = ml.train(X, keep.astype(int), [None] * 140, blocks=BLOCKS)
    assert a is not None and b is not None and b.keep is not None
    assert b.keep.classes == ("keep",)
    assert b.keep_threshold == a.keep_threshold
    assert [p.keep_score for p in ml.predict(b, X)] == [p.keep_score for p in ml.predict(a, X)]


def test_train_predict_both_heads() -> None:
    X, keep = _keep_data(140, 70, seed=5)
    category: list[str | None] = [None] * 140
    for i, row in enumerate(np.flatnonzero(keep)):
        category[row] = "a" if i < 35 else "b"
        X[row, 3 if i < 35 else 4] += 2.0
    m = ml.train(X, keep, category, blocks=BLOCKS)
    assert m is not None and m.keep is not None and m.category is not None
    assert m.category.classes == ("a", "b")
    assert set(m.cv) == {"keep_auc", "category_bacc"}
    assert (m.n_labels, m.n_keep) == (140, 70)
    for p in ml.predict(m, X[:10]):
        assert p.keep_score is not None and 0.0 <= p.keep_score <= 1.0
        assert p.keep == (p.keep_score >= m.keep_threshold)
        assert p.categories is not None
        assert {c for c, _ in p.categories} == {"a", "b"}
        probs = [q for _, q in p.categories]
        assert probs == sorted(probs, reverse=True)
        assert sum(probs) == pytest.approx(1.0, abs=1e-5)


def test_category_head_only_classes_with_30() -> None:
    X, category = _category_data({"a": 40, "b": 30, "c": 29}, seed=0)
    keep = np.ones(len(category), dtype=bool)  # no discards: no keep head
    m = ml.train(X, keep, list(category), blocks=BLOCKS)
    assert m is not None
    assert m.keep is None and m.keep_threshold is None
    assert m.category is not None and m.category.classes == ("a", "b")
    assert set(m.cv) == {"category_bacc"}
    assert (m.n_labels, m.n_keep) == (99, 99)
    preds = ml.predict(m, X[:3])
    assert all(p.keep is None and p.keep_score is None for p in preds)
    assert all({c for c, _ in p.categories or ()} == {"a", "b"} for p in preds)


def test_keep_head_trains_on_the_newest_rows(monkeypatch) -> None:
    """Over MAX_TRAIN_ROWS rows (oldest first), the keep head fits the newest ones, keeps and discards
    together; the category head fits every keep."""
    monkeypatch.setattr(ml, "MAX_TRAIN_ROWS", 140)
    X, keep = _keep_data(200, 100, seed=6)
    category = [("a" if i % 2 else "b") if k else None for i, k in enumerate(keep)]
    fits: list[tuple[np.ndarray, np.ndarray]] = []
    fit = ml.fit_pipeline
    monkeypatch.setattr(ml, "fit_pipeline", lambda X, y, *a: fits.append((X, y)) or fit(X, y, *a))
    m = ml.train(X, keep, category, blocks=BLOCKS)
    assert m is not None and m.keep is not None and m.category is not None
    (Xk, yk), (Xc, yc) = fits
    np.testing.assert_array_equal(Xk, X[-140:])
    assert yk.tolist() == keep[-140:].tolist()
    np.testing.assert_array_equal(Xc, X[keep])
    assert len(yc) == 100
    assert (m.n_labels, m.n_keep) == (140, int(keep[-140:].sum()))


def test_keep_threshold_matches_share() -> None:
    X, keep = _keep_data(300, 90, seed=0)
    m = ml.train(X, keep, [None] * 300, blocks=BLOCKS)
    assert m is not None and m.keep is not None and m.category is None
    assert m.keep_threshold is not None
    assert 0.5 < m.cv["keep_auc"] <= 1.0
    held_out, _ = _keep_data(2000, 600, seed=7)  # same distribution, unseen rows
    share = np.mean([p.keep for p in ml.predict(m, held_out)])
    assert abs(share - 0.3) <= 0.10


def _head(rng: np.random.Generator, k: int, classes: tuple[str, ...]) -> Head:
    f32 = np.float32
    return Head(
        rng.normal(size=D).astype(f32),
        rng.normal(size=(D, k)).astype(f32),
        rng.normal(size=k).astype(f32),
        classes,
    )


def _assert_same_head(a: Head | None, b: Head | None) -> None:
    if a is None or b is None:
        assert a is b
        return
    for x, y in ((a.medians, b.medians), (a.weights, b.weights), (a.bias, b.bias)):
        assert y.dtype == np.float32
        np.testing.assert_array_equal(x, y)
    assert a.classes == b.classes


def test_npz_roundtrip() -> None:
    rng = np.random.default_rng(0)
    models = [
        Model(
            _head(rng, 1, ("keep",)),
            0.43217,
            _head(rng, 3, ("c1", "c2", "c10")),
            n_labels=500,
            n_keep=140,
            cv={"keep_auc": 0.8123, "category_bacc": 0.6912},
        ),
        Model(
            None, None, _head(rng, 2, ("x", "y")), n_labels=80, n_keep=80, cv={"category_bacc": 0.5}
        ),
    ]
    for m in models:
        r = ml.from_npz(ml.to_npz(m))
        _assert_same_head(m.keep, r.keep)
        _assert_same_head(m.category, r.category)
        assert (r.keep_threshold, r.n_labels, r.n_keep, r.cv) == (
            m.keep_threshold,
            m.n_labels,
            m.n_keep,
            m.cv,
        )


CATS = [("c1", 0.6), ("c2", 0.3), ("c3", 0.1)]
ALIVE = {"c1", "c2", "c3"}


def test_first_button_discard_and_category() -> None:
    assert ml.first_button(Prediction(0.1, False, CATS), ALIVE) == "DISCARD"
    assert ml.first_button(Prediction(0.1, False, None), ALIVE) == "DISCARD"
    assert ml.first_button(Prediction(0.9, True, CATS), ALIVE) == "c1"
    assert ml.first_button(Prediction(None, None, CATS), ALIVE) == "c1"  # no keep head
    assert ml.first_button(Prediction(0.9, True, None), ALIVE) is None  # no category head


def test_first_button_skips_dead_category() -> None:
    assert ml.first_button(Prediction(0.9, True, CATS), {"c2", "c3"}) == "c2"
    assert ml.first_button(Prediction(0.9, True, CATS), set()) is None


def test_evaluate_previous_counts() -> None:
    t = T
    labels = [
        Label("t1", "v1", False, None, t),
        Label("t2", "v2", False, None, t),
        Label("t3", "v3", True, "c1", t),
        Label("t4", "v4", True, "c2", t),
        Label("t5", "v5", True, "c9", t),  # alive, but a class the model never knew
    ]
    preds = [
        Prediction(0.2, False, CATS),  # DISCARD: hit
        Prediction(0.7, True, CATS),  # c1 for a discard: miss
        Prediction(0.8, True, CATS),  # c1: hit, top1, top2
        Prediction(0.6, True, CATS),  # c1 for c2: miss, top2 only
        Prediction(0.4, False, CATS),  # DISCARD for a keep: miss, not in top-k
    ]
    got = ml.evaluate_previous(preds, labels, ALIVE | {"c9"})
    assert got == {
        "first_hit": pytest.approx(0.4),
        "first_n": 5,
        "keep_auc": pytest.approx(4 / 6),
        "keep_n": 5,
        "top1": pytest.approx(0.5),
        "top2": pytest.approx(1.0),
        "cat_n": 2,
    }
    empty = dict.fromkeys(("first_hit", "keep_auc", "top1", "top2"))
    assert ml.evaluate_previous([], [], ALIVE) == {**empty, "first_n": 0, "keep_n": 0, "cat_n": 0}
    one_class = ml.evaluate_previous(preds[:2], labels[:2], ALIVE)
    assert one_class["keep_auc"] is None and one_class["keep_n"] == 2


def test_evaluate_previous_skips_unmatchable_keeps() -> None:
    """A keep whose category is not alive (deleted, or None) has no button to match: out of first_*, in keep_*."""
    labels = [
        Label("t1", "v1", True, "gone", T),
        Label("t2", "v2", True, None, T),
        Label("t3", "v3", False, None, T),
    ]
    preds = [Prediction(0.9, True, CATS), Prediction(0.8, True, CATS), Prediction(0.3, False, CATS)]
    got = ml.evaluate_previous(preds, labels, ALIVE)
    assert (got["first_hit"], got["first_n"]) == (1.0, 1)
    assert (got["keep_auc"], got["keep_n"]) == (1.0, 3)


def test_evaluate_previous_topk_skips_dead_category() -> None:
    labels = [Label("t1", "v1", True, "c2", T), Label("t2", "v2", True, "c3", T)]
    preds = [Prediction(0.9, True, CATS)] * 2
    got = ml.evaluate_previous(preds, labels, {"c2", "c3"})  # c1, the model's top pick, is dead
    assert (got["top1"], got["top2"], got["cat_n"]) == (0.5, 1.0, 2)
