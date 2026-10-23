"""Fuzzy scorer tests (Plan 4 Task 4)."""

from __future__ import annotations

import pytest

from collector.providers.base import VendorTrackRef
from collector.settings import reset_settings_cache
from collector.vendor_match.scorer import (
    FuzzyScore,
    artist_named,
    candidate_names_track,
    score_candidate,
    version_rule_accepts,
    version_title_sim,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_settings_cache()
    yield
    reset_settings_cache()


def _candidate(**overrides) -> VendorTrackRef:
    base = dict(
        vendor="spotify",
        vendor_track_id="x",
        isrc=None,
        artist_names=("Foo",),
        title="Bar",
        duration_ms=200_000,
        album_name="Baz",
        raw_payload={},
    )
    base.update(overrides)
    return VendorTrackRef(**base)


def test_perfect_match() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert s.total >= 0.95


def test_title_differs_slightly() -> None:
    cand = _candidate(title="Bar (Remix)")
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert 0.6 <= s.total < 0.95


def test_duration_outside_tolerance_penalises() -> None:
    cand = _candidate(duration_ms=250_000)
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert not s.duration_ok


def test_artist_mismatch() -> None:
    cand = _candidate(artist_names=("Different",))
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert s.artist_sim < 0.5


def test_multi_artist_query_uses_best_pair() -> None:
    cand = _candidate(artist_names=("Foo",))
    s = score_candidate(
        candidate=cand,
        artist="Foo & Bar",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert s.artist_sim == pytest.approx(1.0)


def test_album_bonus_when_match() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert s.album_bonus == pytest.approx(0.05)


def test_album_bonus_zero_when_mismatch() -> None:
    cand = _candidate(album_name="Different")
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert s.album_bonus == 0.0


def test_score_fields_accessible() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert isinstance(s, FuzzyScore)
    assert 0.0 <= s.title_sim <= 1.0
    assert 0.0 <= s.artist_sim <= 1.0
    assert isinstance(s.duration_ok, bool)
    assert 0.0 <= s.total <= 1.0


def test_duration_unknown_is_not_ok() -> None:
    cand = _candidate(duration_ms=None)
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert not s.duration_ok


def test_tolerance_override_via_env(monkeypatch) -> None:
    monkeypatch.setenv("FUZZY_DURATION_TOLERANCE_MS", "60000")
    reset_settings_cache()

    cand = _candidate(duration_ms=250_000)
    s = score_candidate(
        candidate=cand,
        artist="Foo",
        title="Bar",
        duration_ms=200_000,
        album="Baz",
    )
    assert s.duration_ok


# ── version rule (labelled review sample, 2026-10-18) ──────────────────────
# Owner's rule: Original = Radio = Extended are one recording; a remix is not.


def _s(
    title_sim: float, artist_sim: float = 1.0, duration_ok: bool = False, album: bool = False
) -> FuzzyScore:
    album_bonus = 0.05 if album else 0.0
    return FuzzyScore(
        title_sim=title_sim,
        artist_sim=artist_sim,
        duration_ok=duration_ok,
        album_bonus=album_bonus,
        total=round(0.5 * title_sim + 0.4 * artist_sim + 0.05 * duration_ok + album_bonus, 3),
    )


@pytest.mark.parametrize(
    ("title", "mix", "candidate", "score"),
    [
        ("Letting Go", "Extended Mix", "Letting Go", _s(1.0)),  # shorter edit of the same track
        (
            "Over You",
            "Extended Mix",
            "Over You (Extended Mix)",
            _s(0.52, duration_ok=True, album=True),
        ),
        ("Rubedo", "Original Mix", "Rubedo (feat. alba)", _s(0.48, duration_ok=True, album=True)),
        (
            "Everybody Movin, Pt. 2",
            "Guy Schreiner Remix",
            "Everybody Movin, Pt. 2 (Guy Schreiner Remix)",
            _s(0.67, duration_ok=True),
        ),
        ("The Key Keepers", "Radio Mix", "The Key Keepers (Radio Mix)", _s(0.65, duration_ok=True)),
    ],
)
def test_version_rule_accepts_the_same_recording(title, mix, candidate, score) -> None:
    assert version_rule_accepts(candidate_title=candidate, title=title, mix_name=mix, score=score)


@pytest.mark.parametrize(
    ("title", "mix", "candidate", "score"),
    [
        ("The Realm", "Tawa Girl Remix", "The Realm", _s(1.0)),  # the original, not the remix
        (
            "Light in the Dark",
            "Extended Mix",
            "Light in the Dark (Dub Mix)",
            _s(0.77, duration_ok=True),
        ),
        (
            "How Many More",
            "Original Mix",
            "Show Me",
            _s(0.60, duration_ok=True),
        ),  # same length, other track
        ("FIREE", "EXTENDED VIP VIP", "FIREEE", _s(0.91, duration_ok=True)),
        ("Night Drive", "Original Mix", "Night Drive", _s(1.0, artist_sim=0.8)),  # another artist
    ],
)
def test_version_rule_rejects_another_recording(title, mix, candidate, score) -> None:
    assert not version_rule_accepts(
        candidate_title=candidate, title=title, mix_name=mix, score=score
    )


def test_version_title_sim_ignores_unicode_form_and_case() -> None:
    assert version_title_sim("Lunère", "LUNÈRE", None) == 1.0


def test_version_rule_stays_inside_the_labelled_score_range() -> None:
    # Same title and length by another artist (a cover, a namesake "Intro"):
    # below 0.70 nothing was labelled, so the rule does not reach there.
    stranger = FuzzyScore(
        title_sim=1.0, artist_sim=0.1, duration_ok=True, album_bonus=0.0, total=0.59
    )
    assert not version_rule_accepts(
        candidate_title="Intro", title="Intro", mix_name="Original Mix", score=stranger
    )


def test_a_short_title_with_a_long_mix_name_still_passes() -> None:
    # "Cigarro" vs "Cigarro (Promi5E Remix)" scores 0.68 on the plain title;
    # with the mix in, it is an exact match one second off.
    assert version_rule_accepts(
        candidate_title="Cigarro (Promi5E Remix)",
        title="Cigarro",
        mix_name="PROMI5E Remix",
        score=_s(0.47, duration_ok=True),
    )


def test_a_dub_never_takes_the_plain_radio_mix() -> None:
    # "Rush (Dub Radio Mix)": the Radio Mix is as long but is another recording.
    radio = _s(0.40, duration_ok=True)
    dub = _s(0.33, duration_ok=True)
    assert not version_rule_accepts(
        candidate_title="Rush (Radio Mix)", title="Rush", mix_name="Dub Radio Mix", score=radio
    )
    assert version_rule_accepts(
        candidate_title="Rush (Dub Radio Mix)", title="Rush", mix_name="Dub Radio Mix", score=dub
    )


def test_same_title_and_length_by_another_artist_is_refused() -> None:
    # "DjEdyB — After the Drop (Radio Edit)" 4:48 vs "DJ Rusty — After The Drop" 4:48.
    assert not version_rule_accepts(
        candidate_title="After The Drop",
        title="After the Drop (Radio Edit)",
        mix_name="Radio Edit",
        score=_s(0.68, artist_sim=0.43, duration_ok=True),
    )


# ── artist check (no candidate names our artist → not on YouTube) ──────────


@pytest.mark.parametrize(
    ("ours", "cand_title", "cand_artists"),
    [
        (["Dabu"], "Let The Verse Play", ["dabü"]),  # diacritics
        (["Jhana"], "Anatta", ["Jhãna"]),
        (["Air Media", "Nguyễn Đình Vũ"], "Vạn Vật (Remix)", ["Nguyễn Đình Vũ", "VM"]),
        (["Dj SaeRo"], "BAT", ["Deejay SaeRo"]),  # a distinctive word of the name
        (["DJ Icon (US)"], "These Days (Extended Mix)", ["DJ Icon"]),  # country tag
        (["Artem ORVEXA"], "No Look", ["ORVEXA"]),  # alias inside our credit
        (["KVL UA"], "Soltero", ["KvL"]),
        (["Glitch City", "Blaxx"], "Why (feat. Blaxx & Maddy V)", ["Glitch City"]),
        (["Maddy V"], "Why (Radio Mix) (feat. Blaxx & Maddy V)", ["Glitch City"]),  # in title
    ],
)
def test_artist_is_named_despite_spelling(ours, cand_title, cand_artists) -> None:
    assert artist_named(ours, cand_title, cand_artists) is True


def test_strangers_with_the_same_title_do_not_name_the_artist() -> None:
    assert artist_named(["Tenzia"], "Splinter", ["Candiria"]) is False
    assert artist_named(["Baher"], "Time Machine", ["Bergal"]) is False


def test_no_latin_name_cannot_be_judged() -> None:
    assert artist_named(["宝石"], "daylight", ["gem 宝石"]) is None


def test_a_candidate_without_credits_cannot_be_judged() -> None:
    # "Lead Time (Edit)" with no artist at all may still be Vandek's edit.
    assert artist_named(["Vandek"], "Lead Time (Edit)", []) is None
    assert artist_named(["Vandek"], "Lead Time (Vandek Edit)", []) is True


@pytest.mark.parametrize(
    ("ours", "title", "mix", "cand_title", "cand_artists"),
    [
        # A word of the name in someone else's title is not the artist.
        (["Punk Rock"], "Back To You", "Extended Mix", "Back To Punk", ["G Anon"]),
        # The artist named, but on another song of theirs.
        (["Khristian Dax"], "This!", "Original Mix", "White Christmas", ["Dax Hill"]),
        (
            ["Ryan Summer"],
            "U Make Me Want It",
            "Extended Mix",
            "Everything Makes Me Think Of U",
            ["Ryan Shaw"],
        ),
        (["LKNV", "Amancay"], "Bicoastal", "Original Mix", "Camouflage", ["LKNV", "Amancay"]),
    ],
)
def test_a_candidate_names_the_track_only_with_our_artist_and_a_like_title(
    ours, title, mix, cand_title, cand_artists
) -> None:
    assert candidate_names_track(ours, title, mix, cand_title, cand_artists) is False


def test_the_full_name_counts_in_the_title_too() -> None:
    # "feat." credits often live in the title only.
    assert candidate_names_track(
        ["Maddy V"], "Why", "Radio Mix", "Why (Radio Mix) (feat. Blaxx & Maddy V)", ["Glitch City"]
    )


def test_a_credit_less_candidate_stays_unjudged() -> None:
    assert (
        candidate_names_track(["Vandek"], "Lead Time", "Extended Mix", "Lead Time (Edit)", [])
        is None
    )


def test_a_video_titled_artist_dash_title_is_ours() -> None:
    # Video uploads: "Guri - Lost Track (Official Video)" by a label channel.
    assert candidate_names_track(
        ["Guri"], "Lost Track", None, "Guri - Lost Track (Official Video)", ["Some Label"]
    )
