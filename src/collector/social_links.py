"""Three-tier Instagram-first socials resolver.

Ported (logic kept as close to verbatim as the prod adaptation allows) from
the enrichment-split experiment, which ran live against 200 prod entities
(100 labels + 100 artists across two `max_tool_calls` caps):

  - ``experiments/enrichment_split/src/splitlab/social_regex.py``
    (regex patterns, ``_CANON``, ``extract_profiles``, ``handle_of``,
    ``validate_instagram_handle``, ``_norm``).
  - ``experiments/enrichment_split/src/splitlab/tavily_client.py``
    (credit accounting: basic search = 1 credit, extract = ceil(n/5)
    credits).
  - ``experiments/enrichment_split/src/splitlab/facts_pass.py``
    (tier-1/2/3 gating: ``_known_official_urls``, tier conditions,
    results-text joining) -- WITHOUT the LLM numeric-facts extraction,
    which is out of scope for this module.

Provenance and measured results:
``docs/superpowers/specs/2026-07-16-enrichment-split-experiment-report.md``
-- verdict on the "3-tier Instagram/socials module": GO, with one
precision fix, both applied here.

Adaptations vs the experiment (see the report's "Fix" note under
"Key findings" #1):

  1. HTTP goes through ``httpx.Client`` (injectable for tests) instead of
     ``urllib``, matching the prod Tavily-over-httpx pattern used in
     ``collector/label_enrichment/vendors/tavily_deepseek.py`` (POST JSON
     with ``api_key`` in the payload body).
  2. ``validate_instagram_handle`` is applied on ALL tiers (1/2/3), not
     just tier 3 like splitlab did. The experiment measured tier-1
     precision at ~86% without validation; a candidate instagram handle
     found via tier-1/2 regex that fails validation is discarded and the
     resolver falls through to the next tier.
  3. The short-name substring rule in ``validate_instagram_handle`` is
     relaxed from ``len(name) >= 5`` to ``len(name) >= 4`` (fixes
     rejected-but-correct ``agrodnb``/"Agro", ``eneimusique``/"Enei").
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import httpx

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

_SNIPPET_CHARS = 4000


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
    # relaxed vs splitlab (>=5): fixes agrodnb/"Agro", eneimusique/"Enei"
    if len(name) >= 4 and (name in h or h in name):
        return True
    for url in known_profiles.values():
        known = handle_of(url or "")
        if known and _norm(known) == h:
            return True
    return False


class TavilyClient:
    """Thin Tavily REST wrapper over ``httpx.Client`` with deterministic
    credit counting (basic search = 1 credit, extract = ceil(n/5) credits,
    $8 / 1000 credits)."""

    def __init__(
        self,
        api_key: str,
        http: httpx.Client | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=timeout_s)
        self._credits = 0

    @property
    def credits_used(self) -> int:
        return self._credits

    def _post(self, path: str, payload: dict) -> dict:
        resp = self._http.post(f"https://api.tavily.com/{path}", json=payload)
        resp.raise_for_status()
        return resp.json()

    def search(
        self,
        query: str,
        *,
        max_results: int = 8,
        include_raw_content: bool = False,
        include_domains: list[str] | None = None,
    ) -> dict:
        payload: dict = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        self._credits += 1
        return self._post("search", payload)

    def extract(self, urls: list[str]) -> dict:
        if not urls:
            return {"results": []}
        self._credits += math.ceil(len(urls) / 5)
        return self._post("extract", {"api_key": self._api_key, "urls": urls})


def _results_text(results: list[dict]) -> str:
    parts = []
    for r in results:
        parts.append(
            f"URL: {r.get('url', '')}\n"
            f"{(r.get('content') or '')[:500]}\n"
            f"{(r.get('raw_content') or '')[:_SNIPPET_CHARS]}"
        )
    return "\n\n---\n\n".join(parts)


def _known_official_urls(merged: dict) -> list[str]:
    urls: list[str] = []
    for f in ("website", "bandcamp_url", "soundcloud_url"):
        v = merged.get(f)
        if isinstance(v, str) and v.startswith("http") and v not in urls:
            urls.append(v)
    return urls[:5]


@dataclass
class SocialsResult:
    updates: dict[str, str]  # only fields that were empty in `merged` and got a validated/regex value
    instagram_tier: int | None  # 1/2/3 or None
    tavily_credits: int
    error: str | None = None


class SocialsResolver:
    """3-tier instagram-first socials resolution against Tavily.

    Tier 1: one basic search ``"{name}" {style} {noun}`` with
    ``include_raw_content=True``, ``max_results=8`` -> ``extract_profiles``
    over the joined content/raw_content/url text -> validate the instagram
    candidate.

    Tier 2 (only if instagram still missing): ``extract()`` over up to 5
    official URLs from ``merged`` (``website``, ``bandcamp_url``,
    ``soundcloud_url``) -> regex + validate.

    Tier 3 (only if instagram still missing): search restricted to
    ``include_domains=["instagram.com"]``, ``max_results=5`` -> validate
    each result's handle in order, first validated handle wins.
    """

    def __init__(self, tavily_api_key: str, http: httpx.Client | None = None) -> None:
        self._api_key = tavily_api_key
        self._http = http

    def resolve(self, *, kind: str, name: str, style: str, merged: dict) -> SocialsResult:
        """Never raises. No-op result when `merged` already has instagram_url.

        Other social URL fields land in `updates` only where `merged`'s
        value is empty AND the regex found one on official-page content
        (tier 1/2 content).
        """
        if merged.get("instagram_url"):
            return SocialsResult(updates={}, instagram_tier=None, tavily_credits=0)

        try:
            tavily = TavilyClient(self._api_key, http=self._http)
            noun = "record label" if kind == "label" else "artist"
            instagram_tier: int | None = None

            # tier 1: regex over general search content
            search = tavily.search(
                f'"{name}" {style} {noun}', max_results=8, include_raw_content=True
            )
            all_text = _results_text(search.get("results") or [])
            profiles = extract_profiles(all_text)

            candidate = profiles.get("instagram_url")
            if candidate:
                handle = handle_of(candidate)
                if handle and validate_instagram_handle(handle, name, merged):
                    instagram_tier = 1
                else:
                    profiles.pop("instagram_url", None)

            # tier 2: extract known official pages
            if instagram_tier is None:
                known = _known_official_urls(merged)
                if known:
                    extracted = tavily.extract(known)
                    text2 = _results_text(extracted.get("results") or [])
                    found = extract_profiles(text2)
                    candidate2 = found.get("instagram_url")
                    if candidate2:
                        handle2 = handle_of(candidate2)
                        if handle2 and validate_instagram_handle(handle2, name, merged):
                            profiles["instagram_url"] = candidate2
                            instagram_tier = 2
                        else:
                            found.pop("instagram_url", None)
                    for k, v in found.items():
                        profiles.setdefault(k, v)

            # tier 3: targeted instagram search with validation
            if instagram_tier is None:
                topup = tavily.search(
                    f"{name} {style}", max_results=5, include_domains=["instagram.com"]
                )
                for r in topup.get("results") or []:
                    handle3 = handle_of(r.get("url") or "")
                    if handle3 and validate_instagram_handle(handle3, name, profiles):
                        profiles["instagram_url"] = f"https://www.instagram.com/{handle3}"
                        instagram_tier = 3
                        break

            updates: dict[str, str] = {}
            for field, value in profiles.items():
                if not merged.get(field):
                    updates[field] = value

            return SocialsResult(
                updates=updates, instagram_tier=instagram_tier, tavily_credits=tavily.credits_used
            )
        except Exception as exc:  # noqa: BLE001 — resolver must never raise
            return SocialsResult(
                updates={}, instagram_tier=None, tavily_credits=0, error=f"{type(exc).__name__}: {exc}"
            )
