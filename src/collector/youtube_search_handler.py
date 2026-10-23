"""SQS worker: search the catalog on YouTube, one batch an hour.

An hourly EventBridge rule queues one batch (250 tracks). The worker claims the
newest releases not yet searched (clouder_tracks.youtube_searched_at), searches
each at a fixed pace, stores the YT Music match / review / no_match and the
comments video, and hands back what a ban or the deadline cut off for the next
hour. A ban pauses the sweep: hourly batches are dropped until it is over.
"""

from __future__ import annotations

import functools
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .logging_utils import log_event
from .repositories import (
    ClouderRepository,
    UpsertVendorMatchCmd,
    create_clouder_repository_from_env,
    utc_now,
)
from .schemas import YoutubeSearchMessage, validation_error_message
from .settings import YoutubeSearchWorkerSettings, get_youtube_search_worker_settings
from .youtube_search.search import TrackQuery, TrackSearchResult, is_ban, search_track

VENDOR_SONG = "ytmusic"
VENDOR_VIDEO = "youtube"
_DEADLINE_MARGIN_MS = 60_000
# Per request; worst case per track 3 x (2 s pace + 10 s) stays inside the margin.
_REQUEST_TIMEOUT_S = 10
# Search errors in a row before the sweep treats them as a block it cannot
# recognise (ytmusicapi parses JSON before the status: an HTML 429 page is a
# JSONDecodeError, a throttled socket a ReadTimeout).
_ERROR_STREAK = 5
# Aurora (min_acu=0) auto-pauses after 5 min idle, so an hourly batch (or an
# SQS redelivery) often meets a paused cluster, and waking takes longer than the
# Data API retry budget: wait up to ~2 min more before giving the message back.
_DB_WAKE_ATTEMPTS = 12
_DB_WAKE_SLEEP_S = 10


class _ErrorStreak(Exception):
    """Too many failed searches in a row: pause like a ban."""


def _session() -> Any:
    import requests

    session = requests.Session()
    session.request = functools.partial(session.request, timeout=_REQUEST_TIMEOUT_S)  # type: ignore[method-assign]
    return session


def _default_client() -> Any:
    from ytmusicapi import YTMusic  # lazy: cold start pays only when a batch runs

    return YTMusic(requests_session=_session())


class Pacer:
    """Blocks until at least *interval_s* passed since the previous call."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def __call__(self) -> None:
        if self._last is not None:
            wait = self._interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()


def lambda_handler(
    event: Mapping[str, Any],
    context: Any,
    *,
    client_factory: Callable[[], Any] = _default_client,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    remaining_ms = getattr(context, "get_remaining_time_in_millis", None)
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}
    log_event("INFO", "youtube_search_worker_invoked", sqs_record_count=len(records))

    settings = get_youtube_search_worker_settings()
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError(
            "AURORA Data API configuration is required for the YouTube search worker"
        )

    processed = 0
    for index, record in enumerate(records):
        body = record.get("body") if isinstance(record, Mapping) else None
        if not isinstance(body, str):
            continue
        try:
            message = YoutubeSearchMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "youtube_search_message_invalid",
                sqs_record_index=index,
                error_message=validation_error_message(exc),
            )
            continue
        correlation_id = _correlation_id(record)
        _sweep(
            repository,
            settings,
            message,
            correlation_id,
            remaining_ms=remaining_ms,
            client_factory=client_factory,
            sleep=sleep,
        )
        processed += 1
    return {"processed": processed}


def _sweep(
    repository: ClouderRepository,
    settings: YoutubeSearchWorkerSettings,
    message: YoutubeSearchMessage,
    correlation_id: str,
    *,
    remaining_ms: Callable[[], int] | None,
    client_factory: Callable[[], Any],
    sleep: Callable[[float], None],
) -> None:
    blocked_until = _blocked_until_waking_db(repository, correlation_id, sleep)
    # Database only, so even a paused sweep keeps YouTube in step with Spotify.
    log_event(
        "INFO",
        "youtube_reviews_reconciled",
        correlation_id=correlation_id,
        closed=repository.close_youtube_reviews_without_spotify(now=utc_now()),
        reopened=repository.reopen_youtube_for_spotify_found(),
        second_chance=repository.reopen_youtube_second_chance(now=utc_now()),
    )
    now = utc_now()
    if blocked_until is not None and blocked_until > now:
        # YouTube refused us: leave it alone; a later hourly batch goes on.
        log_event(
            "INFO",
            "youtube_search_paused",
            correlation_id=correlation_id,
            retry_after=round((blocked_until - now).total_seconds()),
            reason="trigger_dropped",
        )
        return

    claimed_at = utc_now()
    tracks = repository.claim_tracks_for_youtube_search(
        limit=message.batch_size, claimed_at=claimed_at
    )
    if not tracks:
        log_event(
            "INFO",
            "youtube_search_skipped",
            correlation_id=correlation_id,
            reason="no_tracks_need_search",
        )
        return

    batch_id = uuid4().hex[:12]
    log_event(
        "INFO",
        "youtube_search_tracks_loaded",
        correlation_id=correlation_id,
        batch_id=batch_id,
        track_count=len(tracks),
    )
    pace = Pacer(settings.min_interval_ms / 1000, sleep=sleep)
    tally: Counter[str] = Counter()
    # Failed searches stay claimed until a later success shows YouTube still
    # answers (then they are marked searched); a streak releases them instead.
    unconfirmed: list[str] = []
    try:
        client = client_factory()
        cut_by_deadline = False
        for track in tracks:
            if remaining_ms is not None and remaining_ms() < _DEADLINE_MARGIN_MS:
                cut_by_deadline = True
                break
            if _search_one(repository, client, pace, track, settings, correlation_id, tally):
                for track_id in unconfirmed:
                    repository.mark_youtube_searched(track_id=track_id, at=utc_now())
                unconfirmed.clear()
                continue
            unconfirmed.append(str(track["id"]))
            if len(unconfirmed) >= _ERROR_STREAK:
                raise _ErrorStreak(f"{len(unconfirmed)} searches failed in a row")
        if cut_by_deadline:
            repository.release_youtube_search_claim(claimed_at=claimed_at)
        else:
            for track_id in unconfirmed:  # isolated failures at the batch end
                repository.mark_youtube_searched(track_id=track_id, at=utc_now())
    except Exception as exc:
        repository.release_youtube_search_claim(claimed_at=claimed_at)
        if not (is_ban(exc) or isinstance(exc, _ErrorStreak)):
            raise
        until = utc_now() + timedelta(seconds=settings.ban_seconds)
        repository.set_vendor_blocked_until(VENDOR_SONG, until, utc_now())
        log_event(
            "WARNING",
            "youtube_search_paused",
            correlation_id=correlation_id,
            batch_id=batch_id,
            retry_after=settings.ban_seconds,
            reason="error_streak" if isinstance(exc, _ErrorStreak) else "banned",
            error_message=str(exc)[:300],
        )
        _log_summary(correlation_id, batch_id, tally)
        return

    _log_summary(correlation_id, batch_id, tally)


def _blocked_until_waking_db(
    repository: ClouderRepository, correlation_id: str, sleep: Callable[[float], None]
) -> Any:
    """First DB call of a run, waiting out an Aurora resume."""
    for attempt in range(1, _DB_WAKE_ATTEMPTS + 1):
        try:
            return repository.get_vendor_blocked_until(VENDOR_SONG)
        except Exception as exc:
            code = (getattr(exc, "response", None) or {}).get("Error", {}).get("Code")
            if code != "DatabaseResumingException" or attempt == _DB_WAKE_ATTEMPTS:
                raise
            log_event(
                "INFO",
                "youtube_search_waiting_for_db",
                correlation_id=correlation_id,
                attempt=attempt,
            )
            sleep(_DB_WAKE_SLEEP_S)
    return None  # pragma: no cover - the loop returns or raises


def _search_one(
    repository: ClouderRepository,
    client: Any,
    pace: Pacer,
    track: Mapping[str, Any],
    settings: YoutubeSearchWorkerSettings,
    correlation_id: str,
    tally: Counter[str],
) -> bool:
    """Search and store one track. False = the search itself failed (the caller
    decides whether that was an isolated failure or a block); bans raise."""
    track_id = str(track["id"])
    length = track.get("length_ms")
    query = TrackQuery(
        artists=str(track.get("artists") or ""),
        title=str(track.get("title") or ""),
        duration_ms=int(length) if length is not None else None,
        album=track.get("album_title"),
        need_song=not bool(track.get("has_ytmusic")),
        mix_name=track.get("mix_name"),
        early=bool(track.get("early")),
    )
    try:
        result = search_track(client, query, threshold=settings.fuzzy_match_threshold, pace=pace)
    except Exception as exc:
        if is_ban(exc):
            raise
        tally["errors"] += 1
        log_event(
            "WARNING",
            "youtube_search_result",
            correlation_id=correlation_id,
            track_id=track_id,
            outcome="error",
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:300],
        )
        return False
    try:
        _persist(repository, track_id, result, utc_now())
    except Exception as exc:
        # Bad result data (e.g. a NUL byte jsonb rejects) must not stall the
        # sweep on this track; a real outage fails the mark below and propagates.
        tally["errors"] += 1
        log_event(
            "WARNING",
            "youtube_search_result",
            correlation_id=correlation_id,
            track_id=track_id,
            outcome="error",
            phase="persist",
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:300],
        )
        repository.mark_youtube_searched(track_id=track_id, at=utc_now())
        return True
    repository.mark_youtube_searched(track_id=track_id, at=utc_now())
    tally[result.outcome] += 1
    tally["total_tracks"] += 1
    if result.video is not None:
        tally["videos_found"] += 1
    log_event(
        "INFO",
        "youtube_search_result",
        correlation_id=correlation_id,
        track_id=track_id,
        outcome=result.outcome,
        confidence=result.best_score,
        match_type=_song_match_type(result) if result.match else None,
        reason=result.no_match_reason,
        request_count=result.request_count,
        video_found=result.video is not None,
    )
    return True


def _song_match_type(result: TrackSearchResult) -> str:
    return "fuzzy_version" if result.match_reason == "version_rule" else "fuzzy"


def _persist(
    repository: ClouderRepository, track_id: str, result: TrackSearchResult, now: Any
) -> None:
    if result.video is not None:
        repository.upsert_vendor_match(
            UpsertVendorMatchCmd(
                clouder_track_id=track_id,
                vendor=VENDOR_VIDEO,
                vendor_track_id=result.video.vendor_track_id,
                match_type="token",
                confidence=Decimal("1.000"),
                matched_at=now,
                payload=result.video.raw_payload,
            )
        )
    if not result.song_searched:
        return
    if result.match is not None:
        ref, score = result.match
        repository.upsert_vendor_match(
            UpsertVendorMatchCmd(
                clouder_track_id=track_id,
                vendor=VENDOR_SONG,
                vendor_track_id=ref.vendor_track_id,
                match_type=_song_match_type(result),
                confidence=Decimal(str(score.total)),
                matched_at=now,
                payload=ref.raw_payload,
            )
        )
    elif result.review:
        repository.insert_review_candidate(
            review_id=str(uuid4()),
            clouder_track_id=track_id,
            vendor=VENDOR_SONG,
            candidates=[
                {
                    "ref": r.raw_payload,
                    "score": s.total,
                    "title_sim": s.title_sim,
                    "artist_sim": s.artist_sim,
                    "duration_ok": s.duration_ok,
                    "album_bonus": s.album_bonus,
                }
                for r, s in result.review
            ],
            created_at=now,
        )
    else:
        repository.mark_no_match(clouder_track_id=track_id, vendor=VENDOR_SONG, created_at=now)


def _log_summary(correlation_id: str, batch_id: str, tally: Counter[str]) -> None:
    log_event(
        "INFO",
        "youtube_search_completed",
        correlation_id=correlation_id,
        batch_id=batch_id,
        total_tracks=tally["total_tracks"],
        auto=tally["auto"],
        review=tally["review"],
        no_match=tally["no_match"],
        errors=tally["errors"],
        videos_found=tally["videos_found"],
    )


def _correlation_id(record: Mapping[str, Any]) -> str:
    attrs = record.get("messageAttributes")
    if isinstance(attrs, Mapping):
        value = attrs.get("correlation_id")
        if isinstance(value, Mapping) and isinstance(value.get("stringValue"), str):
            return value["stringValue"]
    return str(uuid4())
