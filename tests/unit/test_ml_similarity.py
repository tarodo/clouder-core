"""The similar-tracks vector: MuLan + EffNet embedding of a light-1 profile through the frozen PCA."""

from __future__ import annotations

import numpy as np

from collector import audio_profile
from collector.ml import similarity as sim

rng = np.random.default_rng(7)


def _profiles(n: int) -> np.ndarray:
    return rng.standard_normal((n, audio_profile.DIMS)).astype(np.float32)


def test_used_takes_mulan_then_effnet_embedding() -> None:
    X = _profiles(3)
    U = sim.used(X)
    assert U.shape == (3, 1792)
    np.testing.assert_array_equal(U[:, :512], X[:, 1680:2192])
    np.testing.assert_array_equal(U[:, 512:], X[:, 400:1680])


def test_embed_is_unit_256_and_deterministic() -> None:
    X = _profiles(300)
    art = sim.fit(X)
    keep, V = sim.embed(art, X)
    assert keep.all() and V.shape == (300, sim.DIMS) and V.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(V, axis=1), 1, atol=1e-5)
    np.testing.assert_array_equal(sim.embed(art, X)[1], V)


def test_embed_ignores_unused_arrays() -> None:
    X = _profiles(300)
    art = sim.fit(X)
    Y = X.copy()
    Y[:, 0:400] = 5  # effnet/discogs400
    Y[:, 2192:16528] = -3  # MuQ
    np.testing.assert_array_equal(sim.embed(art, Y)[1], sim.embed(art, X)[1])


def test_npz_round_trip() -> None:
    art = sim.fit(_profiles(300))
    back = sim.from_npz(sim.to_npz(art))
    for name in ("mulan_mean", "effnet_mean", "mean", "components"):
        np.testing.assert_array_equal(getattr(back, name), getattr(art, name))


def test_embed_drops_degenerate_rows() -> None:
    X = _profiles(300)
    art = sim.fit(X)
    Y = X[:5].copy()
    Y[1, 1680:2192] = art.mulan_mean  # MuLan at its mean: zero after centring
    Y[2, 500] = np.nan
    Y[4, 400:1680] = 0  # an all-zero EffNet block: centring alone would make it -mean, a fake point
    keep, V = sim.embed(art, Y)
    assert keep.tolist() == [True, False, False, True, False]
    # BLAS rounds a 5-row and a 2-row product differently in the last bits (OpenBLAS on CI)
    np.testing.assert_allclose(V, sim.embed(art, Y[[0, 3]])[1], atol=1e-6)


def test_fit_ignores_degenerate_rows() -> None:
    X = _profiles(300)
    Y = X.copy()
    Y[:50, 1680:2192] = 0  # zero MuLan blocks must not drag the mean
    np.testing.assert_allclose(sim.fit(Y).mulan_mean, X[50:, 1680:2192].mean(axis=0), atol=1e-6)


def test_as_text_parses_back() -> None:
    v = sim.embed(sim.fit(_profiles(300)), _profiles(1))[1][0]
    text = sim.as_text(v)
    assert text.startswith("[") and text.endswith("]")
    parsed = np.array([float(x) for x in text[1:-1].split(",")], dtype=np.float32)
    assert parsed.shape == (256,)
    np.testing.assert_allclose(parsed, v, atol=1e-4)
