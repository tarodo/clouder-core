"""Deterministic profile-URL extraction from page text and handle validation."""

from __future__ import annotations

import re

_NON_PROFILE_IG = {"p", "reel", "reels", "explore", "stories", "accounts", "share", "tv"}
_HANDLE = r"[A-Za-z0-9_.\-]{2,60}"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "instagram_url": re.compile(rf"instagram\.com/({_HANDLE})"),
    "twitter_url": re.compile(rf"(?:^|[^a-z0-9.])(?:www\.)?(?:twitter|x)\.com/({_HANDLE})", re.IGNORECASE),
    "soundcloud_url": re.compile(rf"soundcloud\.com/({_HANDLE})"),
    "beatport_url": re.compile(rf"beatport\.com/label/({_HANDLE})"),
    "residentadvisor_url": re.compile(rf"ra\.co/labels/({_HANDLE})"),
    "discogs_url": re.compile(rf"discogs\.com/label/({_HANDLE})"),
    "bandcamp_url": re.compile(rf"({_HANDLE})\.bandcamp\.com"),
}

_CANON = {
    "instagram_url": "https://www.instagram.com/{h}",
    "twitter_url": "https://x.com/{h}",
    "soundcloud_url": "https://soundcloud.com/{h}",
    "beatport_url": "https://www.beatport.com/label/{h}",
    "residentadvisor_url": "https://ra.co/labels/{h}",
    "discogs_url": "https://www.discogs.com/label/{h}",
    "bandcamp_url": "https://{h}.bandcamp.com",
}

_TWITTER_SKIP = {"intent", "share", "search", "hashtag", "home", "i"}


def extract_profiles(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for field, pattern in _PATTERNS.items():
        for handle in pattern.findall(text):
            h = handle.rstrip(".")
            if field == "instagram_url" and h.lower() in _NON_PROFILE_IG:
                continue
            if field == "twitter_url" and h.lower() in _TWITTER_SKIP:
                continue
            out[field] = _CANON[field].format(h=h)
            break
    return out


def extract_instagram(text: str) -> str | None:
    return extract_profiles(text).get("instagram_url")


def handle_of(url: str) -> str | None:
    parts = [p for p in url.split("?")[0].split("/") if p]
    if not parts:
        return None
    tail = parts[-1]
    if ".bandcamp.com" in url:
        m = re.search(r"https?://([^./]+)\.bandcamp\.com", url)
        return m.group(1) if m else None
    return tail or None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def validate_instagram_handle(
    handle: str, entity_name: str, known_profiles: dict[str, str]
) -> bool:
    h = _norm(handle)
    if not h:
        return False
    name = _norm(entity_name)
    # strip generic suffixes so "defiantxrecords" matches "Defiant"
    for stem in (name, name + "records", name + "recs", name + "music", name + "official"):
        if h == stem:
            return True
    if len(name) >= 5 and (name in h or h in name):
        return True
    for url in known_profiles.values():
        known = handle_of(url or "")
        if known and _norm(known) == h:
            return True
    return False
