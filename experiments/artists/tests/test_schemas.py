import pytest
from pydantic import ValidationError

from artlab.schemas import (
    AIContentStatus,
    AISignal,
    AISignalKind,
    ArtistInfo,
    ArtistType,
)


def test_artist_info_minimal_valid():
    info = ArtistInfo(
        artist_name="ANNA",
        ai_reasoning="No AI signals found in available sources.",
        summary="Brazilian techno DJ and producer.",
        confidence=0.9,
    )
    assert info.artist_name == "ANNA"
    assert info.artist_type == ArtistType.UNKNOWN
    assert info.ai_content == AIContentStatus.UNKNOWN
    assert info.aliases == []
    assert info.labels == []


def test_artist_info_full():
    info = ArtistInfo(
        artist_name="Aiva Nova",
        country="US",
        active_since=2024,
        artist_type=ArtistType.SOLO,
        ai_content=AIContentStatus.CONFIRMED,
        ai_signals=[
            AISignal(
                kind=AISignalKind.NO_LIVE_PRESENCE,
                description="No gigs, tours, or RA dates found.",
                source_url="https://example.com/checked",
            ),
        ],
        ai_reasoning="No live presence plus AI-looking imagery.",
        summary="Likely synthetic AI persona.",
        confidence=0.8,
    )
    assert info.artist_type == ArtistType.SOLO
    assert info.ai_signals[0].kind == AISignalKind.NO_LIVE_PRESENCE


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        ArtistInfo(artist_name="x", ai_reasoning="x", summary="x", confidence=1.5)
    with pytest.raises(ValidationError):
        ArtistInfo(artist_name="x", ai_reasoning="x", summary="x", confidence=-0.1)


def test_artist_info_app_fields_optional():
    info = ArtistInfo(artist_name="ANNA", ai_reasoning="-", summary="-", confidence=0.5)
    assert info.spotify_url is None
    assert info.bio is None
    assert info.tagline is None


def test_artist_info_accepts_links_and_bio():
    info = ArtistInfo(
        artist_name="ANNA",
        spotify_url="https://open.spotify.com/artist/abc",
        bio="Brazilian techno producer and DJ.",
        ai_reasoning="-",
        summary="-",
        confidence=0.6,
    )
    assert info.spotify_url == "https://open.spotify.com/artist/abc"
    assert info.bio == "Brazilian techno producer and DJ."
