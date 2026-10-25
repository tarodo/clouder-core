"""Triage decisions as training rows (spec §4)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class Label:
    track_id: str
    video_id: str
    keep: bool
    category_id: str | None  # None: a discard, or a keep whose category is soft-deleted
    added_at: datetime


def training_rows(
    labels: Iterable[Label],
) -> tuple[list[str], np.ndarray, list[str | None]]:
    """One row per video, oldest first by its newest label; a video whose tracks disagree on keep or on
    category is dropped."""
    decisions: dict[str, set[tuple[bool, str | None]]] = {}
    newest: dict[str, datetime] = {}
    for label in labels:
        decisions.setdefault(label.video_id, set()).add((label.keep, label.category_id))
        newest[label.video_id] = max(label.added_at, newest.get(label.video_id, label.added_at))
    rows = sorted(
        ((video_id, *d.pop()) for video_id, d in decisions.items() if len(d) == 1),
        key=lambda r: newest[r[0]],
    )
    return (
        [r[0] for r in rows],
        np.array([r[1] for r in rows], dtype=bool),
        [r[2] for r in rows],
    )
