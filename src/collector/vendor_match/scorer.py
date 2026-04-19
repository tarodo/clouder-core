"""Fuzzy candidate scorer for vendor_match_worker."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..providers.base import VendorTrackRef
from ..settings import get_vendor_match_settings


@dataclass(frozen=True)
class FuzzyScore:
    title_sim: float
    artist_sim: float
    duration_ok: bool
    album_bonus: float
    total: float


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


def _string_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _best_artist_sim(candidate_artists: tuple[str, ...], query_artist: str) -> float:
    if not candidate_artists:
        return 0.0
    parts = [p.strip() for p in query_artist.replace("&", ",").split(",") if p.strip()]
    if not parts:
        parts = [query_artist]
    best = 0.0
    for cand in candidate_artists:
        for q in parts:
            best = max(best, _string_sim(cand, q))
    return best


def score_candidate(
    *,
    candidate: VendorTrackRef,
    artist: str,
    title: str,
    duration_ms: int | None,
    album: str | None,
) -> FuzzyScore:
    title_sim = _string_sim(candidate.title, title)
    artist_sim = _best_artist_sim(candidate.artist_names, artist)

    tolerance = get_vendor_match_settings().fuzzy_duration_tolerance_ms
    duration_ok = False
    if duration_ms is not None and candidate.duration_ms is not None:
        duration_ok = abs(candidate.duration_ms - duration_ms) <= tolerance

    album_bonus = 0.0
    if album and candidate.album_name and _normalize(album) == _normalize(candidate.album_name):
        album_bonus = 0.05

    duration_contribution = 0.05 if duration_ok else 0.0
    total = min(
        1.0,
        0.5 * title_sim + 0.4 * artist_sim + duration_contribution + album_bonus,
    )

    return FuzzyScore(
        title_sim=title_sim,
        artist_sim=artist_sim,
        duration_ok=duration_ok,
        album_bonus=album_bonus,
        total=round(total, 3),
    )
