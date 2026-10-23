"""Per-user triage heads (spec §5): the lab's `ablation.pipeline()`, folded into one linear map per head.

Training ports the lab: median impute, standardise, block weights 1/sqrt(width), PCA onto the train rows (an exact
rotation of the row space: L2 logistic regression predicts the same, and each fit is ~n_train-dimensional), then
LogisticRegressionCV. Unlike the lab's `matrix()`, constant and all-NaN columns stay, so the layout keeps every column:
the imputer keeps empty features (as 0) and the scaler leaves zero-variance columns at scale 1.
"""

from __future__ import annotations

import io
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.special import expit, softmax
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from collector import audio_profile
from collector.ml.labels import Label

CS = np.logspace(-4, 4, 9)
MAX_ITER = 5000
SCORING = {"keep": "roc_auc", "category": "balanced_accuracy"}
KEEP_MIN_LABELS = 130
KEEP_MIN_EACH = 35  # keeps and discards
CATEGORY_MIN = 30  # rows per class; a category head needs >= 2 such classes
DISCARD = "DISCARD"


@dataclass(frozen=True, eq=False)
class Head:
    """logits = (X - medians, NaN -> 0) @ weights + bias. K == 1: P(keep) by sigmoid; else softmax over classes.

    Centred on the medians: float32 summing raw X against a bias that cancels large column means loses digits."""

    medians: np.ndarray  # (d,)
    weights: np.ndarray  # (d, K)
    bias: np.ndarray  # (K,) the logits at the medians
    classes: tuple[str, ...]

    def proba(self, X: np.ndarray) -> np.ndarray:
        Z = X - self.medians
        Z[np.isnan(Z)] = 0
        z = Z @ self.weights + self.bias
        return expit(z) if z.shape[1] == 1 else softmax(z, axis=1)


@dataclass(frozen=True, eq=False)
class Model:
    keep: Head | None
    keep_threshold: float | None  # set iff keep is
    category: Head | None
    n_labels: int
    n_keep: int
    cv: dict[
        str, float
    ]  # inner-CV best scores: "keep_auc", "category_bacc" (each only if that head trained)


@dataclass(frozen=True)
class Prediction:
    keep_score: float | None
    keep: bool | None
    categories: list[tuple[str, float]] | None  # every class, p descending


def block_weights(blocks: Sequence[tuple[str, int, int]], d: int) -> np.ndarray:
    w = np.zeros(d)
    for _name, offset, width in blocks:
        w[offset : offset + width] = 1 / np.sqrt(width)
    return w


def _weigh(Z: np.ndarray, w: np.ndarray) -> np.ndarray:
    return Z * w


def _folds(seed: int) -> StratifiedKFold:
    return StratifiedKFold(3, shuffle=True, random_state=seed)


def _preprocess(w: np.ndarray) -> list[Any]:
    return [
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        FunctionTransformer(_weigh, kw_args={"w": w}),
        PCA(),
    ]


def fit_pipeline(X: np.ndarray, y: np.ndarray, w: np.ndarray, task: str, seed: int = 0) -> Pipeline:
    lr = LogisticRegressionCV(
        Cs=CS,
        cv=_folds(seed),
        scoring=SCORING[task],
        max_iter=MAX_ITER,
        class_weight="balanced" if task == "category" else None,
    )
    return make_pipeline(*_preprocess(w), lr).fit(X, y)


def collapse(pipe: Pipeline) -> Head:
    """Fold imputer, scaler, block weights, PCA and the LR into one Head (a bool target is the keep head)."""
    imputer, scaler, weigh, pca, lr = (step for _, step in pipe.steps)
    s = weigh.kw_args["w"] / scaler.scale_  # standardised and weighted: x * s - mean * s
    m = pca.components_.T @ lr.coef_.T  # (d, K)
    b = lr.intercept_
    if lr.classes_.dtype == bool:
        classes: tuple[str, ...] = ("keep",)
    else:
        classes = tuple(str(c) for c in lr.classes_)
        if m.shape[1] == 1:  # binary: softmax([0, a]) == (1 - sigmoid(a), sigmoid(a))
            m, b = np.hstack([np.zeros_like(m), m]), np.r_[0.0, b]
    medians = imputer.statistics_.astype(np.float32)
    bias = b + ((medians - scaler.mean_) * s - pca.mean_) @ m  # float64: the logits at the medians
    return Head(medians, (s[:, None] * m).astype(np.float32), bias.astype(np.float32), classes)


def _best_score(lr: LogisticRegressionCV) -> float:
    """The inner-CV score of the chosen C (scores_ holds one (folds, Cs) array per class, all equal)."""
    return float(next(iter(lr.scores_.values())).mean(axis=0).max())


def train(
    X: np.ndarray,
    keep: np.ndarray,
    category: Sequence[str | None],
    *,
    blocks: Sequence[tuple[str, int, int]] = audio_profile.BLOCKS,
    seed: int = 0,
) -> Model | None:
    """Rows are videos (`labels.training_rows`). None when neither head reaches its threshold."""
    # A bool target is what makes `collapse` build the keep head.
    keep = np.asarray(keep, dtype=bool)
    w = block_weights(blocks, X.shape[1])
    n, n_keep = len(keep), int(keep.sum())
    cv: dict[str, float] = {}
    keep_head: Head | None = None
    threshold: float | None = None
    if n >= KEEP_MIN_LABELS and min(n_keep, n - n_keep) >= KEEP_MIN_EACH:
        pipe = fit_pipeline(X, keep, w, "keep", seed)
        keep_head, cv["keep_auc"] = collapse(pipe), _best_score(pipe[-1])
        # Out-of-fold P(keep) at the chosen C; its (1 - keep share) quantile predicts keeps at the label share.
        oof = cross_val_predict(
            make_pipeline(*_preprocess(w), LogisticRegression(C=pipe[-1].C_[0], max_iter=MAX_ITER)),
            X,
            keep,
            cv=_folds(seed),
            method="predict_proba",
        )[:, 1]
        threshold = float(np.quantile(oof, 1 - keep.mean()))
    counts = Counter(c for c in category if c is not None)
    classes = {c for c, k in counts.items() if k >= CATEGORY_MIN}
    category_head: Head | None = None
    if len(classes) >= 2:
        rows = np.array([c in classes for c in category])
        y = np.array([c for c in category if c in classes])
        pipe = fit_pipeline(X[rows], y, w, "category", seed)
        category_head, cv["category_bacc"] = collapse(pipe), _best_score(pipe[-1])
    if keep_head is None and category_head is None:
        return None
    return Model(keep_head, threshold, category_head, n, n_keep, cv)


def predict(model: Model, X: np.ndarray) -> list[Prediction]:
    keep, threshold, head = model.keep, model.keep_threshold, model.category
    scores = keep.proba(X)[:, 0].tolist() if keep is not None else None
    probs = head.proba(X).tolist() if head is not None else None
    out = []
    for i in range(len(X)):
        score = scores[i] if scores is not None else None
        out.append(
            Prediction(
                score,
                None if score is None or threshold is None else score >= threshold,
                None
                if probs is None or head is None
                else sorted(zip(head.classes, probs[i], strict=True), key=lambda t: -t[1]),
            )
        )
    return out


def to_npz(model: Model) -> bytes:
    meta = {
        "keep_threshold": model.keep_threshold,
        "n_labels": model.n_labels,
        "n_keep": model.n_keep,
        "cv": model.cv,
    }
    arrays: dict[str, Any] = {"meta": np.array(json.dumps(meta))}
    for name, head in (("keep", model.keep), ("category", model.category)):
        if head is not None:
            arrays |= {
                f"{name}_medians": head.medians,
                f"{name}_weights": head.weights,
                f"{name}_bias": head.bias,
                f"{name}_classes": np.array(head.classes),
            }
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def from_npz(data: bytes) -> Model:
    with np.load(io.BytesIO(data)) as z:
        meta = json.loads(z["meta"].item())
        keep, category = (
            Head(
                z[f"{n}_medians"],
                z[f"{n}_weights"],
                z[f"{n}_bias"],
                tuple(z[f"{n}_classes"].tolist()),
            )
            if f"{n}_medians" in z
            else None
            for n in ("keep", "category")
        )
    return Model(
        keep, meta["keep_threshold"], category, meta["n_labels"], meta["n_keep"], meta["cv"]
    )


def _ranking(pred: Prediction, alive: set[str]) -> list[str]:
    return [c for c, _ in pred.categories or () if c in alive]


def first_button(pred: Prediction, alive: set[str]) -> str | None:
    """The primary lit button (spec §6): DISCARD for a predicted discard, else the top alive category."""
    if pred.keep is False:
        return DISCARD
    return next(iter(_ranking(pred, alive)), None)


def _share(hits: list[bool]) -> float | None:
    return sum(hits) / len(hits) if hits else None


def evaluate_previous(
    preds: list[Prediction], labels: list[Label], alive: set[str]
) -> dict[str, Any]:
    """The previous model's stored predictions against the labels added since (parallel lists).

    first_*: the first button equals the decision (DISCARD, or the keep's category). A keep whose category is not
    alive (soft-deleted, or None) has no button to match and is left out. keep_*: AUC of keep_score.
    top1/top2: keeps in a class the model knew, ranked among the alive categories.
    """
    first, scored, tops = [], [], []
    for pred, label in zip(preds, labels, strict=True):
        if not label.keep:
            first.append(first_button(pred, alive) == DISCARD)
        elif label.category_id in alive:
            first.append(first_button(pred, alive) == label.category_id)
        if pred.keep_score is not None:
            scored.append((label.keep, pred.keep_score))
        if label.keep and label.category_id in {c for c, _ in pred.categories or ()}:
            top = _ranking(pred, alive)[:2]
            tops.append((label.category_id in top[:1], label.category_id in top))
    ys = [y for y, _ in scored]
    auc = float(roc_auc_score(ys, [s for _, s in scored])) if len(set(ys)) == 2 else None
    return {
        "first_hit": _share(first),
        "first_n": len(first),
        "keep_auc": auc,
        "keep_n": len(scored),
        "top1": _share([t1 for t1, _ in tops]),
        "top2": _share([t2 for _, t2 in tops]),
        "cat_n": len(tops),
    }
