"""Tests for Spotify metadata-fallback scoring + accept gate."""

from __future__ import annotations

from collector.spotify_client import _accept_metadata_match


def test_accept_match_passes_strict_thresholds() -> None:
    assert _accept_metadata_match(
        title_sim=0.92,
        artist_sim=0.88,
        candidate_duration_ms=180_000,
        query_duration_ms=181_500,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_low_title_sim() -> None:
    assert not _accept_metadata_match(
        title_sim=0.89,
        artist_sim=0.99,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_low_artist_sim() -> None:
    assert not _accept_metadata_match(
        title_sim=1.0,
        artist_sim=0.84,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_rejects_duration_outside_tolerance() -> None:
    assert not _accept_metadata_match(
        title_sim=1.0,
        artist_sim=1.0,
        candidate_duration_ms=180_000,
        query_duration_ms=184_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_passes_when_query_duration_unknown() -> None:
    assert _accept_metadata_match(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=180_000,
        query_duration_ms=None,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )


def test_accept_passes_when_candidate_duration_unknown() -> None:
    assert _accept_metadata_match(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=None,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )
