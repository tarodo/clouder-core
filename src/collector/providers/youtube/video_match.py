"""Token-set matcher for picking a regular YouTube video for a track.

YouTube `videos` results expose the uploading channel as the "artist" and embed
the artist in the title ("Artist - Title"), so the vendor-match fuzzy scorer is
unusable here. Instead require every meaningful query word (artist + title) to
appear in the candidate title (coverage == 1.0), and require the version markers
to match (so an original track does not match a remix video, and vice versa).
"""

from __future__ import annotations

import re

_STOPWORDS = {"the", "a", "an", "of", "in", "on", "and", "to"}

_NOISE = {
    "official", "video", "audio", "lyric", "lyrics", "hd", "hq", "4k", "mv",
    "visualizer", "visualiser", "premiere", "ft", "feat", "featuring", "music",
    "clip", "free", "download", "out", "now", "prod",
}

_VERSION_MARKERS = {
    "remix", "edit", "bootleg", "mashup", "rework", "flip", "vip", "instrumental",
    "acapella", "acappella", "live", "cover", "version", "remaster", "remastered",
    "sped", "slowed", "karaoke", "dub", "extended", "radio", "mix",
}


def _tokens(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split() if w]


def _versions(tokens: set[str]) -> set[str]:
    v = _VERSION_MARKERS & tokens
    # "original mix"/"original version" denotes the original, not a distinct version.
    if "original" in tokens:
        v -= {"mix", "version"}
    return v


def video_matches(query_artist: str, query_title: str, candidate_title: str) -> bool:
    q_all = set(_tokens(query_artist) + _tokens(query_title))
    c_all = set(_tokens(candidate_title))

    # Coverage compares CONTENT words only. Version descriptors (remix/edit/mix/
    # …/"original") are excluded here and enforced separately by the version
    # guard below — otherwise a Beatport-style title like "Disposition (Original
    # Mix)" would require the YouTube title to repeat "original"/"mix". The
    # remixer name (e.g. "klute") is NOT a marker, so it stays as content.
    descriptors = _VERSION_MARKERS | {"original"}
    q_sig = q_all - _STOPWORDS - _NOISE - descriptors
    c_sig = c_all - _NOISE
    if not q_sig:
        return False

    coverage = q_sig <= c_sig
    version_ok = _versions(q_all) == _versions(c_all)
    return coverage and version_ok
