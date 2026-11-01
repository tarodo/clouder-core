"""The similar-tracks vector (spec 2026-11-01): MuLan + EffNet embedding of a light-1 profile, each
centred and unit-normalised, concatenated, projected onto a frozen PCA and normalised again; cosine
distance ranks it. The artifact is fitted once per VERSION and never overwritten: vectors of two
fits are not comparable."""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np

from collector import audio_profile
from collector.repositories.similarity import VERSION

ARTIFACT_KEY = f"models/similarity/{VERSION}.npz"
DIMS = 256
SAMPLE = 10_000  # fit sample: the first profiled videos by video_id (random ids, every style)

_ARRAYS = {name: (offset, width) for name, offset, width in audio_profile.ARRAYS}
_MULAN = _ARRAYS["mulan/mix.clips"]
_EFFNET = _ARRAYS["effnet/embedding"]
_FLOOR = 1e-9


@dataclass(frozen=True)
class Artifact:
    mulan_mean: np.ndarray  # (512,)
    effnet_mean: np.ndarray  # (1280,)
    mean: np.ndarray  # (1792,) of the normalised concat
    components: np.ndarray  # (DIMS, 1792)


def used(X: np.ndarray) -> np.ndarray:
    """(n, 1792) float32: MuLan then the EffNet embedding, out of full profiles (n, DIMS)."""
    (mo, mw), (eo, ew) = _MULAN, _EFFNET
    return np.concatenate([X[:, mo : mo + mw], X[:, eo : eo + ew]], axis=1).astype(np.float32)


def _unit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rows scaled to length 1, and which rows had a finite, non-zero length."""
    with np.errstate(invalid="ignore", over="ignore"):
        norms = np.linalg.norm(X, axis=1, keepdims=True)
    ok = np.isfinite(norms[:, 0]) & (norms[:, 0] > _FLOOR)
    return X / np.where(ok[:, None], norms, 1), ok


def _concat(U: np.ndarray, mulan_mean: np.ndarray, effnet_mean: np.ndarray):
    m, ok_m = _unit(U[:, :512] - mulan_mean)
    e, ok_e = _unit(U[:, 512:] - effnet_mean)
    z, ok_z = _unit(np.concatenate([m, e], axis=1))
    return z, ok_m & ok_e & ok_z


def _used(X: np.ndarray) -> np.ndarray:
    return used(X) if X.shape[1] == audio_profile.DIMS else X.astype(np.float32)


def fit(X: np.ndarray) -> Artifact:
    """The artifact from a sample of profiles (n, DIMS) or of their used columns (n, 1792)."""
    U = _used(X)
    mulan_mean = U[:, :512].mean(axis=0)
    effnet_mean = U[:, 512:].mean(axis=0)
    Z, ok = _concat(U, mulan_mean, effnet_mean)
    Z = Z[ok]
    mean = Z.mean(axis=0)
    _, _, vt = np.linalg.svd(Z - mean, full_matrices=False)
    components = np.zeros((DIMS, Z.shape[1]), dtype=np.float32)
    components[: min(DIMS, len(vt))] = vt[:DIMS]
    return Artifact(
        mulan_mean.astype(np.float32),
        effnet_mean.astype(np.float32),
        mean.astype(np.float32),
        components,
    )


def embed(art: Artifact, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(kept rows mask (n,), their vectors (k, DIMS) float32). A row that is non-finite or zero at
    any normalisation is dropped: pgvector rejects NaN and a zero vector has no cosine."""
    Z, ok = _concat(_used(X), art.mulan_mean, art.effnet_mean)
    with np.errstate(invalid="ignore", over="ignore"):
        P, ok_p = _unit((Z - art.mean) @ art.components.T)
    keep = ok & ok_p
    return keep, P[keep].astype(np.float32)


def to_npz(art: Artifact) -> bytes:
    buf = io.BytesIO()
    np.savez(
        buf,
        mulan_mean=art.mulan_mean,
        effnet_mean=art.effnet_mean,
        mean=art.mean,
        components=art.components,
    )
    return buf.getvalue()


def from_npz(blob: bytes) -> Artifact:
    with np.load(io.BytesIO(blob)) as z:
        return Artifact(z["mulan_mean"], z["effnet_mean"], z["mean"], z["components"])


def as_text(v: np.ndarray) -> str:
    """pgvector text input: 4 significant digits are plenty for ranking."""
    return "[" + ",".join(f"{x:.4g}" for x in v.tolist()) + "]"
