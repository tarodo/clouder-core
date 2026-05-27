import pytest
from pydantic import ValidationError

from collector.artist_enrichment.schemas import (
    AIContentStatus,
    AISignal,
    AISignalKind,
    ArtistInfo,
    ArtistType,
)


def test_minimal_valid():
    info = ArtistInfo(artist_name="ANNA", ai_reasoning="none", summary="Brazilian techno DJ.", confidence=0.9)
    assert info.artist_name == "ANNA"
    assert info.artist_type == ArtistType.UNKNOWN
    assert info.ai_content == AIContentStatus.UNKNOWN
    assert info.labels == []


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        ArtistInfo(artist_name="x", ai_reasoning="x", summary="x", confidence=1.5)


def test_ai_signal_and_links():
    info = ArtistInfo(
        artist_name="Aiva Nova",
        active_since=2024,
        spotify_url="https://open.spotify.com/artist/x",
        ai_content=AIContentStatus.SUSPECTED,
        ai_signals=[AISignal(kind=AISignalKind.NO_LIVE_PRESENCE, description="no gigs")],
        ai_reasoning="no presence",
        summary="synthetic",
        confidence=0.6,
    )
    assert info.active_since == 2024
    assert info.ai_signals[0].kind == AISignalKind.NO_LIVE_PRESENCE
    assert info.spotify_url.endswith("/x")
