"""Tests for Spotify metadata-fallback scoring + accept gate."""

from __future__ import annotations

import json
from unittest.mock import patch

from collector.spotify_client import (
    SpotifyClient,
    _first_query_artist,
    _isrc_neighbours,
    _match_tier,
    _normalize_title_for_match,
)


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_client() -> SpotifyClient:
    c = SpotifyClient(
        client_id="x", client_secret="y", sleep_fn=lambda _: None,
    )
    c._access_token = "tok"
    c._token_expires_at = 9e18
    return c


def _spotify_track(
    *, sp_id: str, name: str, artists: list[str],
    duration_ms: int, isrc: str = "ZZZ123",
) -> dict:
    return {
        "id": sp_id,
        "name": name,
        "artists": [{"name": a} for a in artists],
        "duration_ms": duration_ms,
        "external_ids": {"isrc": isrc},
        "album": {"release_date": "2026-01-01", "release_date_precision": "day"},
    }


def test_first_query_artist_strips_country_suffix() -> None:
    assert _first_query_artist("Kays (UK)") == "Kays"
    assert _first_query_artist("Artist (US)") == "Artist"
    assert _first_query_artist("Some One (USA)") == "Some One"


def test_first_query_artist_takes_first_of_comma_list() -> None:
    assert _first_query_artist("Kays (UK), Nixxy Rain") == "Kays"
    assert (
        _first_query_artist("Alessandro Pierozzi, Luca Belotti")
        == "Alessandro Pierozzi"
    )


def test_first_query_artist_takes_first_of_ampersand_list() -> None:
    assert _first_query_artist("Foo & Bar") == "Foo"
    assert _first_query_artist("Above & Beyond") == "Above"


def test_first_query_artist_solo_artist_unchanged() -> None:
    assert _first_query_artist("Rudimental") == "Rudimental"


def test_first_query_artist_handles_empty() -> None:
    assert _first_query_artist("") == ""
    assert _first_query_artist("   ") == ""


def test_isrc_neighbours_returns_closest_first_within_0_9() -> None:
    # 4 → 3, 5, 2, 6 (delta order: -1, +1, -2, +2 == closest first)
    assert _isrc_neighbours("GBKQU2633814") == [
        "GBKQU2633815",  # +1
        "GBKQU2633813",  # -1
        "GBKQU2633816",  # +2
        "GBKQU2633812",  # -2
    ]


def test_isrc_neighbours_skips_negative_when_last_is_zero() -> None:
    # last=0: -1 invalid, +1=1; -2 invalid, +2=2
    assert _isrc_neighbours("GBKQU2633810") == ["GBKQU2633811", "GBKQU2633812"]


def test_isrc_neighbours_skips_carry_when_last_is_nine() -> None:
    # last=9: +1=10 invalid (no carry), -1=8; +2=11 invalid, -2=7
    assert _isrc_neighbours("GBKQU2633819") == ["GBKQU2633818", "GBKQU2633817"]


def test_isrc_neighbours_returns_empty_when_last_not_digit() -> None:
    assert _isrc_neighbours("GBKQU263381X") == []
    assert _isrc_neighbours("") == []


def test_normalize_title_strips_radio_edit_suffix() -> None:
    assert _normalize_title_for_match("Fealty - Radio Edit") == "fealty"


def test_normalize_title_strips_extended_mix_suffix() -> None:
    assert _normalize_title_for_match("Move On - Extended Mix") == "move on"


def test_normalize_title_strips_original_mix_suffix() -> None:
    assert _normalize_title_for_match("Bombay (Original Mix)") == "bombay"


def test_normalize_title_strips_remix_suffix() -> None:
    assert _normalize_title_for_match("Walk Away (Koven Remix)") == "walk away"
    assert _normalize_title_for_match("Walk Away [Koven Remix]") == "walk away"


def test_normalize_title_strips_feat_clause() -> None:
    assert _normalize_title_for_match("Shut Em Down feat. Ragga Twins") == "shut em down"
    assert _normalize_title_for_match("Shut Em Down (feat. Ragga Twins)") == "shut em down"
    assert _normalize_title_for_match("Shut Em Down ft. Ragga Twins") == "shut em down"


def test_normalize_title_collapses_whitespace_and_lowers() -> None:
    assert _normalize_title_for_match("  Move   On  ") == "move on"


def test_normalize_title_leaves_clean_titles_unchanged() -> None:
    assert _normalize_title_for_match("Metropolis") == "metropolis"


def test_normalize_title_handles_empty() -> None:
    assert _normalize_title_for_match("") == ""


def test_match_tier_strict_when_dur_within_tolerance() -> None:
    assert _match_tier(
        title_sim=0.92,
        artist_sim=0.88,
        candidate_duration_ms=180_000,
        query_duration_ms=181_500,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    ) == "strict"


def test_match_tier_fail_when_title_below_min() -> None:
    assert _match_tier(
        title_sim=0.89,
        artist_sim=0.99,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    ) == "fail"


def test_match_tier_fail_when_artist_below_min() -> None:
    assert _match_tier(
        title_sim=1.0,
        artist_sim=0.84,
        candidate_duration_ms=180_000,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    ) == "fail"


def test_match_tier_relaxed_when_dur_outside_but_near_perfect_text() -> None:
    """title>=0.95 AND artist>=0.95 → accept as 'relaxed' regardless of duration delta.
    Same track, different master (radio edit / extended)."""
    assert _match_tier(
        title_sim=1.0,
        artist_sim=1.0,
        candidate_duration_ms=180_000,
        query_duration_ms=255_000,  # 75s out
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    ) == "relaxed"


def test_match_tier_fail_when_dur_out_and_text_not_perfect() -> None:
    """title=0.92, artist=0.92 — pass min thresholds but below 0.95 relaxed gate.
    Without strict-duration backup, must fail to avoid wrong-track matches."""
    assert _match_tier(
        title_sim=0.92,
        artist_sim=0.92,
        candidate_duration_ms=180_000,
        query_duration_ms=240_000,  # 60s out
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    ) == "fail"


def test_match_tier_strict_when_query_duration_unknown() -> None:
    """Cannot enforce duration if either side is None — collapse to strict pass."""
    assert _match_tier(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=180_000,
        query_duration_ms=None,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    ) == "strict"


def test_match_tier_strict_when_candidate_duration_unknown() -> None:
    assert _match_tier(
        title_sim=0.95,
        artist_sim=0.90,
        candidate_duration_ms=None,
        query_duration_ms=180_000,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    ) == "strict"


def test_search_by_metadata_picks_best_when_passes_gate() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="sp_match",
                    name="Move On",
                    artists=["Guri & Eider"],
                    duration_ms=180_000,
                    isrc="GBKQU2633815",
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        result = client._search_by_metadata(
            title="Move On",
            artist="Guri & Eider",
            duration_ms=181_000,
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert result is not None
    track, tier = result
    assert track["id"] == "sp_match"
    assert tier == "strict"


def test_search_by_metadata_returns_none_when_no_items() -> None:
    client = _make_client()
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp({"tracks": {"items": []}}),
    ):
        track = client._search_by_metadata(
            title="Nothing", artist="Nobody", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert track is None


def test_search_by_metadata_returns_none_when_all_fail_gate() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="bad",
                    name="Totally Different Song",
                    artists=["Other Person"],
                    duration_ms=180_000,
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        track = client._search_by_metadata(
            title="Move On", artist="Guri & Eider", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert track is None


def test_search_by_metadata_returns_none_for_empty_inputs() -> None:
    client = _make_client()
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        side_effect=AssertionError("must not be called"),
    ):
        assert client._search_by_metadata(
            title="", artist="Some Artist", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        ) is None
        assert client._search_by_metadata(
            title="Some Title", artist="", duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        ) is None


def test_search_tracks_invokes_metadata_fallback_on_isrc_miss() -> None:
    client = _make_client()

    fallback_track = _spotify_track(
        sp_id="sp_fallback",
        name="Move On",
        artists=["Guri & Eider"],
        duration_ms=180_000,
    )

    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _Resp({"tracks": {"items": []}})
        return _Resp({"tracks": {"items": [fallback_track]}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {
                    "clouder_track_id": "ct1",
                    "isrc": "GBKQU2633814",
                    "title": "Move On",
                    "artists": "Guri & Eider",
                    "duration_ms": 180_000,
                }
            ],
            correlation_id="cid",
            metadata_fallback_enabled=True,
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )

    assert len(results) == 1
    assert results[0].spotify_id == "sp_fallback"
    assert call_count["n"] == 2


def test_search_tracks_skips_fallback_when_flag_off() -> None:
    client = _make_client()
    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {
                    "clouder_track_id": "ct1",
                    "isrc": "GBKQU2633814",
                    "title": "Move On",
                    "artists": "Guri & Eider",
                    "duration_ms": 180_000,
                }
            ],
            correlation_id="cid",
            metadata_fallback_enabled=False,
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert len(results) == 1
    assert results[0].spotify_id is None
    assert call_count["n"] == 1


def test_search_tracks_skips_fallback_without_metadata() -> None:
    client = _make_client()
    call_count = {"n": 0}

    def fake_urlopen(request, timeout=None):
        call_count["n"] += 1
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {
                    "clouder_track_id": "ct1",
                    "isrc": "GBKQU2633814",
                }
            ],
            correlation_id="cid",
            metadata_fallback_enabled=True,
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert len(results) == 1
    assert results[0].spotify_id is None
    assert call_count["n"] == 1


def test_search_by_metadata_uses_first_artist_in_query() -> None:
    """Query string must use first artist with country tag stripped, not full list."""
    client = _make_client()
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        client._search_by_metadata(
            title="Secret Lover",
            artist="Kays (UK), Nixxy Rain",
            duration_ms=180_000,
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    # urlencoded: spaces are '+' and ':' is '%3A'
    assert "track%3ASecret+Lover" in captured["url"]
    assert "artist%3AKays" in captured["url"]
    assert "Nixxy" not in captured["url"]
    assert "%28UK%29" not in captured["url"]  # no "(UK)"


def test_search_by_metadata_returns_relaxed_tier_when_dur_diff_but_text_perfect() -> None:
    """Same track / different master: title 1.0 + artist 1.0, duration 75s out → relaxed."""
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="sp_radio_master",
                    name="Universum",
                    artists=["TERRAZZA", "Wra1th"],
                    duration_ms=215_000,  # 75s shorter than BP's 290_000
                    isrc="UKACT2674300",
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        result = client._search_by_metadata(
            title="Universum",
            artist="TERRAZZA, Wra1th",
            duration_ms=290_000,
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert result is not None
    track, tier = result
    assert track["id"] == "sp_radio_master"
    assert tier == "relaxed"


def test_search_by_metadata_picks_strict_over_relaxed_when_both_present() -> None:
    """If both strict and relaxed candidates exist, strict wins."""
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="relaxed_winner_combined",
                    name="Universum",
                    artists=["TERRAZZA", "Wra1th"],
                    duration_ms=215_000,  # dur out, but title+artist 1.0 → relaxed
                ),
                _spotify_track(
                    sp_id="strict_pick",
                    name="Universum",
                    artists=["TERRAZZA"],  # artist 1.0 still
                    duration_ms=290_000,  # dur ok → strict
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        result = client._search_by_metadata(
            title="Universum",
            artist="TERRAZZA, Wra1th",
            duration_ms=290_000,
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert result is not None
    track, tier = result
    assert tier == "strict"
    assert track["id"] == "strict_pick"


def test_search_by_metadata_normalizes_title_suffix() -> None:
    """Spotify's 'Fealty - Radio Edit' should match BP's 'Fealty' after normalization."""
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="sp_radio",
                    name="Fealty - Radio Edit",
                    artists=["Krisna Artha"],
                    duration_ms=180_000,
                    isrc="GB8KE2609780",
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        result = client._search_by_metadata(
            title="Fealty",
            artist="Krisna Artha",
            duration_ms=181_000,
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )
    assert result is not None
    track, _tier = result
    assert track["id"] == "sp_radio"


def test_search_by_isrc_neighbours_finds_byteflip_match() -> None:
    """ISRC GBKQU2633814 has no track; +1 sibling GBKQU2633815 is the actual master."""
    client = _make_client()
    sibling = _spotify_track(
        sp_id="sp_byteflip",
        name="Move On",
        artists=["Guri & Eider"],
        duration_ms=180_000,
        isrc="GBKQU2633815",
    )
    call_log = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        call_log.append(url)
        if "isrc%3AGBKQU2633815" in url:  # +1 hit
            return _Resp({"tracks": {"items": [sibling]}})
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        track = client._search_by_isrc_neighbours(
            isrc="GBKQU2633814",
            title="Move On",
            artist="Guri & Eider",
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
        )
    assert track is not None
    assert track["id"] == "sp_byteflip"


def test_search_by_isrc_neighbours_rejects_when_title_artist_dont_match() -> None:
    """Sibling ISRC may belong to a totally different track in the same release —
    must reject if title/artist similarity is below the gate."""
    client = _make_client()
    sibling = _spotify_track(
        sp_id="sp_other_track",
        name="Completely Different Song",
        artists=["Different Artist"],
        duration_ms=180_000,
        isrc="GBKQU2633815",
    )

    def fake_urlopen(request, timeout=None):
        return _Resp({"tracks": {"items": [sibling]}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        track = client._search_by_isrc_neighbours(
            isrc="GBKQU2633814",
            title="Move On",
            artist="Guri & Eider",
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
        )
    assert track is None


def test_search_by_isrc_neighbours_returns_none_when_all_neighbours_empty() -> None:
    client = _make_client()

    def fake_urlopen(request, timeout=None):
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        track = client._search_by_isrc_neighbours(
            isrc="GBKQU2633814",
            title="Move On",
            artist="Guri & Eider",
            correlation_id="cid",
            title_min=0.90,
            artist_min=0.85,
        )
    assert track is None


def test_search_tracks_invokes_isrc_neighbours_before_metadata() -> None:
    """ISRC miss → neighbour hit → metadata search NOT issued."""
    client = _make_client()
    sibling = _spotify_track(
        sp_id="sp_neighbour",
        name="Move On",
        artists=["Guri & Eider"],
        duration_ms=180_000,
        isrc="GBKQU2633815",
    )

    call_log: list[str] = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        call_log.append(url)
        if "isrc%3AGBKQU2633815" in url:
            return _Resp({"tracks": {"items": [sibling]}})
        return _Resp({"tracks": {"items": []}})

    with patch("collector.spotify_client.urllib.request.urlopen", fake_urlopen):
        results = client.search_tracks_by_isrc(
            tracks=[
                {
                    "clouder_track_id": "ct1",
                    "isrc": "GBKQU2633814",
                    "title": "Move On",
                    "artists": "Guri & Eider",
                    "duration_ms": 180_000,
                }
            ],
            correlation_id="cid",
            metadata_fallback_enabled=True,
            title_min=0.90,
            artist_min=0.85,
            duration_tolerance_ms=3000,
        )

    assert len(results) == 1
    assert results[0].spotify_id == "sp_neighbour"
    # No q=track:... search should have been issued
    assert not any("q=track" in u for u in call_log)


def test_search_by_metadata_picks_highest_combined_when_multiple_pass() -> None:
    client = _make_client()
    payload = {
        "tracks": {
            "items": [
                _spotify_track(
                    sp_id="ok_but_lower",
                    name="Move On (Original)",
                    artists=["Guri Eider"],
                    duration_ms=180_500,
                ),
                _spotify_track(
                    sp_id="best",
                    name="Move On",
                    artists=["Guri & Eider"],
                    duration_ms=181_000,
                ),
            ]
        }
    }
    with patch(
        "collector.spotify_client.urllib.request.urlopen",
        return_value=_Resp(payload),
    ):
        result = client._search_by_metadata(
            title="Move On", artist="Guri & Eider", duration_ms=181_000,
            correlation_id="cid",
            title_min=0.90, artist_min=0.85, duration_tolerance_ms=3000,
        )
    assert result is not None
    track, _tier = result
    assert track["id"] == "best"
