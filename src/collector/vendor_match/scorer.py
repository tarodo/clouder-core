"""Fuzzy candidate scorer for vendor_match_worker."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
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


def string_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def best_artist_sim(candidate_artists: tuple[str, ...], query_artist: str) -> float:
    if not candidate_artists:
        return 0.0
    parts = [p.strip() for p in query_artist.replace("&", ",").split(",") if p.strip()]
    if not parts:
        parts = [query_artist]
    # Also compare against the unsplit query, so a candidate carrying a single
    # combined artist (e.g. Spotify's "Guri & Eider") matches a multi-artist
    # query string symmetrically.
    full = query_artist.strip()
    if full and full not in parts:
        parts.append(full)
    best = 0.0
    for cand in candidate_artists:
        for q in parts:
            best = max(best, string_sim(cand, q))
    return best


def score_candidate(
    *,
    candidate: VendorTrackRef,
    artist: str,
    title: str,
    duration_ms: int | None,
    album: str | None,
) -> FuzzyScore:
    title_sim = string_sim(candidate.title, title)
    artist_sim = best_artist_sim(candidate.artist_names, artist)

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


# ── Version rule (docs/data/entity-resolution.md, labelled 2026-10-18) ─────
# The catalog title carries no version (mix_name is separate) and YouTube Music
# titles often do, so a correct candidate can score below the threshold while a
# remix's original scores 0.900. The owner treats Original, Radio and Extended
# as one recording; a remix, dub, VIP and the like are other recordings.
GENERIC_VERSIONS = frozenset(
    {
        "original mix",
        "extended mix",
        "radio mix",
        "radio edit",
        "original",
        "extended",
        "original version",
        "extended version",
        "radio version",
    }
)
_OTHER_VERSION = re.compile(
    r"\b(remix|dub|vip|rework|bootleg|instrumental|acapella|a cappella|live|slowed|sped up)\b"
)
_FEAT = re.compile(
    r"[(\[]\s*(?:feat\.?|ft\.?|featuring)\s[^)\]]*[)\]]|\s(?:feat\.?|ft\.?|featuring)\s.*$",
    re.IGNORECASE,
)
_GENERIC_PAREN = re.compile(
    r"[(\[]\s*(?:" + "|".join(sorted(GENERIC_VERSIONS, key=len, reverse=True)) + r")\s*[)\]]",
    re.IGNORECASE,
)
VERSION_RULE_MIN_TITLE_SIM = 0.95
VERSION_RULE_MIN_SCORE = 0.70  # the lowest labelled band, on the version-aware score
# Same title and length by another artist happens ("After the Drop" 4:48 by DJ Rusty
# for DjEdyB's); labelled same-recording matches go down to 0.62 (feat. lists, aliases).
VERSION_RULE_MIN_ARTIST_SIM = 0.6


def _fold(s: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", s or "").casefold().split())


def _core(s: str) -> str:
    return _fold(_GENERIC_PAREN.sub(" ", _FEAT.sub(" ", s)))


def version_title_sim(candidate_title: str, title: str, mix_name: str | None) -> float:
    """Title similarity that knows about versions: compares the candidate with
    our title alone and with "title (mix)", with and without feat. credits and
    generic version tags."""
    ours = [title, f"{title} ({mix_name})"] if mix_name else [title]
    best = 0.0
    for t in ours:
        best = max(
            best,
            SequenceMatcher(None, _fold(candidate_title), _fold(t)).ratio(),
            SequenceMatcher(None, _core(candidate_title), _core(t)).ratio(),
        )
    return best


def version_rule_accepts(
    *, candidate_title: str, title: str, mix_name: str | None, score: FuzzyScore
) -> bool:
    """Auto-accept below the threshold when the candidate is the same recording:
    exact title and artist with a generic version (lengths differ between
    edits), or a matching length with a near-exact version-aware title. Never
    when one side names a version (remix, dub, ...) the other lacks, or when
    the candidate lacks our remix's name."""
    mix = _fold(mix_name)
    cand = _fold(candidate_title)
    # Both ways: a dub is not the radio mix, and the radio mix is not a dub.
    if set(_OTHER_VERSION.findall(cand)) != set(_OTHER_VERSION.findall(_fold(f"{title} {mix}"))):
        return False
    if "remix" in mix:
        remixer = mix.replace("remix", "").strip()
        if not remixer or remixer not in cand:
            return False
    title_sim = version_title_sim(candidate_title, title, mix_name)
    # The floor reads the score with the version-aware title: the plain-title
    # score of a short title sinks under a long mix name ("Rush" vs
    # "Rush (Dub Radio Mix)" is 0.33) though the match is exact.
    version_total = (
        0.5 * title_sim
        + 0.4 * score.artist_sim
        + (0.05 if score.duration_ok else 0.0)
        + score.album_bonus
    )
    if version_total < VERSION_RULE_MIN_SCORE:
        return False
    same_edit_family = (
        (not mix or mix in GENERIC_VERSIONS) and title_sim >= 0.999 and score.artist_sim >= 0.999
    )
    same_length = (
        score.duration_ok
        and title_sim >= VERSION_RULE_MIN_TITLE_SIM
        and score.artist_sim >= VERSION_RULE_MIN_ARTIST_SIM
    )
    return same_edit_family or same_length


# ── Artist check (owner's idea, 2026-10-23) ────────────────────────────────
# A review whose candidates never name our artist is a track YouTube does not
# have. Names are compared leniently, since a miss closes a track: diacritics
# and country tags dropped, a distinctive word of the name enough, an alias
# inside our credit accepted. Labelled same-recording matches all pass.
_LATIN_FOLD = str.maketrans(
    {"đ": "d", "ø": "o", "ł": "l", "ß": "ss", "æ": "ae", "œ": "oe", "þ": "th"}
)
_GENERIC_NAME_WORDS = frozenset(
    {"feat", "with", "remix", "music", "official", "records", "band", "project"}
)
_TAG = re.compile(r"\s*[(\[][^)\]]*[)\]]")


def _name_words(s: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", (s or "").casefold().translate(_LATIN_FOLD))
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", plain)


def artist_named(
    our_artists: Sequence[str], candidate_title: str, candidate_artists: Sequence[str]
) -> bool | None:
    """Does the candidate name one of our artists, in its title or credits?
    None when there is nothing to judge by: no name of ours in Latin letters,
    or a candidate without credits that does not name us in its title."""
    names = [w for w in (_name_words(_TAG.sub(" ", a)) for a in our_artists) if w]
    if not names:
        return None
    # The full name counts in the title too ("feat." credits often live there).
    hay = f" {' '.join(_name_words(candidate_title + ' ' + ' '.join(candidate_artists)))} "
    if any(f" {' '.join(w)} " in hay for w in names):
        return True
    credit_words = [_name_words(a) for a in candidate_artists]
    if not any(credit_words):
        return None  # no credits: the title alone cannot rule our artist out
    # A single word of the name only in the credits: "punk" of "Punk Rock" in
    # someone's title "Back To Punk" is not the artist.
    distinctive = {t for w in names for t in w if len(t) >= 4 and t not in _GENERIC_NAME_WORDS}
    if distinctive & {t for w in credit_words for t in w}:
        return True
    ours = f" {' '.join(t for w in names for t in w)} "
    return any(len("".join(w)) >= 3 and f" {' '.join(w)} " in ours for w in credit_words)


# Owner's labelled same-recording matches go down to 0.57; another song of the
# same artist ("White Christmas" for "This!") sits at 0.34.
ARTIST_CHECK_MIN_TITLE_SIM = 0.5


def candidate_names_track(
    our_artists: Sequence[str],
    title: str,
    mix_name: str | None,
    candidate_title: str,
    candidate_artists: Sequence[str],
) -> bool | None:
    """Is the candidate our track by its artist and title? The artist alone is
    not enough: another song of theirs on YouTube says nothing of this one.
    None when the artist cannot be judged (see artist_named)."""
    named = artist_named(our_artists, candidate_title, candidate_artists)
    if named is None:
        return None
    sims = [version_title_sim(candidate_title, title, mix_name)]
    # Video uploads read "Artist - Title (Official Video)".
    cand = f" {' '.join(_name_words(candidate_title))} "
    for artist in our_artists:
        words = _name_words(_TAG.sub(" ", artist))
        if words and f" {' '.join(words)} " in cand:
            sims.append(version_title_sim(candidate_title, f"{artist} - {title}", mix_name))
    return named and max(sims) >= ARTIST_CHECK_MIN_TITLE_SIM
