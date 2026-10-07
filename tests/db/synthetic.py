"""Deterministic Beatport-shaped raw tracks for canonicalization tests and benchmarks.

Shape follows one production week of a single style: ~1.22 artists per track
(115,330 links / 94,736 tracks in the 2026-10 catalog), ~2.2 tracks per release,
an artist pool of 0.6 x tracks and a label pool of 0.15 x tracks. The ratios are
assumptions, documented in docs/benchmarks/canonicalization.md.
"""

from __future__ import annotations

import random
from typing import Any


def synthetic_week(tracks: int, *, seed: int = 42, style_id: int = 1) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    n_releases = max(1, round(tracks / 2.2))
    n_labels = max(1, round(tracks * 0.15))
    n_artists = max(2, round(tracks * 0.6))
    label_of_release = [rng.randrange(n_labels) for _ in range(n_releases)]

    raw: list[dict[str, Any]] = []
    for track_id in range(1, tracks + 1):
        release = rng.randrange(n_releases)
        label = label_of_release[release]
        artists = rng.sample(range(n_artists), 2 if rng.random() < 0.22 else 1)
        raw.append(
            {
                "id": track_id,
                "name": f"Track {track_id}",
                "mix_name": "Original Mix",
                "isrc": f"QZ{track_id:010d}",
                "bpm": rng.randint(120, 175),
                "length_ms": rng.randint(180_000, 420_000),
                "publish_date": "2026-09-26",
                "artists": [{"id": 1_000_000 + a, "name": f"Artist {a}"} for a in artists],
                "genre": {"id": style_id, "name": f"Style {style_id}"},
                "release": {
                    "id": 2_000_000 + release,
                    "name": f"Release {release}",
                    "label": {"id": 3_000_000 + label, "name": f"Label {label}"},
                },
            }
        )
    return raw
