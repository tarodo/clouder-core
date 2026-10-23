"""One YouTube lookup per track: the YT Music song match and a regular video
for comments, from a single unfiltered ytmusicapi search where possible.

Pure: no DB, no SQS. The caller passes the client and a `pace` callable that
blocks until the next request may go out."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ytmusicapi.exceptions import YTMusicGatedError, YTMusicServerError

from ..providers.base import VendorTrackRef
from ..providers.youtube.video_match import video_matches
from ..providers.ytmusic.normalize import build_query, result_to_ref
from ..vendor_match.scorer import (
    FuzzyScore,
    candidate_names_track,
    same_version,
    score_candidate,
    version_rule_accepts,
)

SEARCH_LIMIT = 10
REVIEW_TOP_N = 5

Scored = tuple[VendorTrackRef, FuzzyScore]


@dataclass(frozen=True)
class TrackQuery:
    artists: str
    title: str
    duration_ms: int | None
    album: str | None
    need_song: bool
    mix_name: str | None = None
    # Searched within the second-chance window after release: YouTube may not
    # carry the track yet, so its review waits for the second search.
    early: bool = False


@dataclass
class TrackSearchResult:
    song_searched: bool
    video: VendorTrackRef | None = None
    match: Scored | None = None
    review: list[Scored] = field(default_factory=list)
    request_count: int = 0
    match_reason: str | None = None  # "version_rule" when accepted below threshold
    no_match_reason: str | None = None  # "artist_absent": no candidate names our artist

    @property
    def outcome(self) -> str:
        if not self.song_searched:
            return "video_only"
        if self.match is not None:
            return "auto"
        return "review" if self.review else "no_match"

    @property
    def best_score(self) -> float | None:
        if self.match is not None:
            return self.match[1].total
        return self.review[0][1].total if self.review else None


def is_ban(exc: BaseException) -> bool:
    """YouTube refusing us (rate limit, forbidden, "are you a bot" gate)."""
    if isinstance(exc, YTMusicGatedError):
        return True
    if isinstance(exc, YTMusicServerError):
        message = str(exc)
        return "HTTP 429" in message or "HTTP 403" in message
    return False


def _refs(raw_results: Any, result_type: str | None) -> list[VendorTrackRef]:
    out: list[VendorTrackRef] = []
    for raw in raw_results or []:
        if not isinstance(raw, dict):
            continue
        if result_type is not None and raw.get("resultType") != result_type:
            continue
        ref = result_to_ref(raw)
        if ref is not None:
            out.append(ref)
    return out


def _scored(refs: list[VendorTrackRef], q: TrackQuery) -> list[Scored]:
    scored = [
        (
            r,
            score_candidate(
                candidate=r,
                artist=q.artists,
                title=q.title,
                duration_ms=q.duration_ms,
                album=q.album,
            ),
        )
        for r in refs
    ]
    scored.sort(key=lambda p: p[1].total, reverse=True)
    return scored


def search_track(
    client: Any, q: TrackQuery, *, threshold: float, pace: Callable[[], None]
) -> TrackSearchResult:
    res = TrackSearchResult(song_searched=q.need_song)

    def call(query: str, filter_name: str | None) -> Any:
        pace()
        res.request_count += 1
        return client.search(query, filter=filter_name, limit=SEARCH_LIMIT)

    # Dash form: better `videos` recall (2026-06-21 video-aware match design).
    first = call(f"{q.artists} - {q.title}".strip(" -"), None)
    res.video = next(
        (v for v in _refs(first, "video") if video_matches(q.artists, q.title, v.title)),
        None,
    )
    if not q.need_song:
        return res

    first_songs = _scored(_refs(first, "song"), q)
    scored = first_songs
    if not (scored and scored[0][1].total >= threshold):
        query = build_query(q.artists, q.title)
        refs = _refs(call(query, "songs"), None)
        if not refs:  # today's vendor-match fallback
            refs = _refs(call(query, "videos"), None)
        # Keep the first answer's songs as candidates too, so empty retries
        # never turn a reviewable track into a permanent no_match.
        seen = {r.vendor_track_id for r in refs}
        scored = _scored(refs + [r for r, _ in first_songs if r.vendor_track_id not in seen], q)

    top = scored[0] if scored else None
    if top and top[1].total >= threshold and same_version(top[0].title, q.title, q.mix_name):
        res.match = top
        return res
    # Below the threshold the best candidate is often the other version (the
    # original of a remix); the right one can sit lower, so try each in order.
    versioned = next(
        (
            pair
            for pair in scored
            if version_rule_accepts(
                candidate_title=pair[0].title, title=q.title, mix_name=q.mix_name, score=pair[1]
            )
        ),
        None,
    )
    if versioned is not None:
        res.match, res.match_reason = versioned, "version_rule"
    elif not q.early and _no_candidate_is_ours(scored, q):
        res.no_match_reason = "artist_absent"
    else:
        res.review = scored[:REVIEW_TOP_N]
    return res


def _no_candidate_is_ours(scored: list[Scored], q: TrackQuery) -> bool:
    """Candidates exist and none is our artist with a like title (owner: "the
    artist is nowhere in the results, so the track is not there")."""
    ours = [a for a in q.artists.split(", ") if a]
    verdicts = [
        candidate_names_track(ours, q.title, q.mix_name, ref.title, ref.artist_names)
        for ref, _ in scored
    ]
    return bool(verdicts) and all(v is False for v in verdicts)
