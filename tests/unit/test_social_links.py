"""Tests for collector.social_links, ported from the enrichment-split
experiment (experiments/enrichment_split/tests/test_social_regex.py,
tests/test_facts_pass.py) plus new coverage for the prod adaptations:
validation applied on all tiers (not just tier 3) and the relaxed
short-name rule. See src/collector/social_links.py's module docstring
for full provenance.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.schemas import LabelInfo
from collector.social_links import (
    SocialsResolver,
    SocialsResult,
    extract_instagram,
    extract_profiles,
    handle_of,
    validate_instagram_handle,
)

BANDCAMP_PAGE = """
Anarkick Records. Hard techno label.
[Instagram](https://www.instagram.com/anarkick_records) |
<a href="https://anarkickrecs.bandcamp.com/music">music</a>
https://soundcloud.com/anarkickrecs
"""

NOISE_PAGE = """
https://www.instagram.com/p/B42256SBSFa/ deep link to a post
https://www.instagram.com/reel/xyz123/ and a reel
instagram.com/explore/tags/techno
"""


def _http_with(responses: list[dict]):
    """Fake httpx.Client-like object: .post() replies with each `responses`
    dict in order (queued), httpx-style (.raise_for_status() + .json())."""
    http = MagicMock()
    http.post.side_effect = [
        SimpleNamespace(raise_for_status=lambda: None, json=lambda body=r: body)
        for r in responses
    ]
    return http


# --- ported from experiments/enrichment_split/tests/test_social_regex.py ---


def test_extract_profiles_finds_instagram_and_soundcloud():
    p = extract_profiles(BANDCAMP_PAGE)
    assert p["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert p["soundcloud_url"] == "https://soundcloud.com/anarkickrecs"
    assert p["bandcamp_url"] == "https://anarkickrecs.bandcamp.com"


def test_post_and_reel_links_are_not_profiles():
    assert extract_instagram(NOISE_PAGE) is None


def test_handle_of():
    assert handle_of("https://www.instagram.com/anarkick_records") == "anarkick_records"
    assert handle_of("https://soundcloud.com/audiocorestudio") == "audiocorestudio"


def test_validate_by_name_similarity():
    assert validate_instagram_handle("anarkick_records", "Anarkick Records", {})
    assert validate_instagram_handle("defiantxrecords", "Defiant", {})
    assert not validate_instagram_handle("ugra.music1111", "Audiocore Production", {})


def test_validate_by_cross_network_match():
    known = {"soundcloud_url": "https://soundcloud.com/audiocorestudio"}
    assert validate_instagram_handle("audiocorestudio", "Audiocore Production", known)


def test_validate_cross_network_skips_non_string_values_from_real_payload():
    """Orchestrators pass known_profiles=merged_info.model_dump(), which mixes
    in lists/ints/enums alongside the url strings (e.g. aliases, founded_year).
    A non-string value must be skipped, not crash handle_of()."""
    dump = LabelInfo(
        label_name="Audiocore Production",
        summary="s",
        confidence=0.5,
        founded_year=1996,
        aliases=["AC"],
        soundcloud_url="https://soundcloud.com/audiocorestudio",
    ).model_dump()
    assert validate_instagram_handle("audiocorestudio", "Audiocore Production", dump) is True


def test_twitter_not_confused_with_other_x_domains():
    assert "twitter_url" not in extract_profiles("watch https://netflix.com/watch/12345 now")
    assert "twitter_url" not in extract_profiles("track https://www.fedex.com/track/9999")
    p = extract_profiles("follow https://x.com/anarkick and https://twitter.com/other")
    assert p["twitter_url"] == "https://x.com/anarkick"


def test_beatport_ra_discogs_profiles():
    text = (
        "https://www.beatport.com/label/drumcode/1234 "
        "https://ra.co/labels/2311 "
        "https://www.discogs.com/label/527509-Anarkick-Records"
    )
    p = extract_profiles(text)
    assert p["beatport_url"] == "https://www.beatport.com/label/drumcode"
    assert p["residentadvisor_url"] == "https://ra.co/labels/2311"
    assert p["discogs_url"] == "https://www.discogs.com/label/527509-Anarkick-Records"


# --- new: relaxed short-name rule (task 4 precision fix) ---


def test_short_name_validation_relaxed():
    assert validate_instagram_handle("agrodnb", "Agro", {})
    assert validate_instagram_handle("eneimusique", "Enei", {})
    assert not validate_instagram_handle("ugra.music1111", "Audiocore Production", {})


# --- tier gating, adapted from tests/test_facts_pass.py (no LLM here) ---


def test_tier1_instagram_from_raw_content():
    http = _http_with([
        {"results": [{
            "url": "https://x.example",
            "raw_content": "see https://www.instagram.com/anarkick_records ok",
            "content": "Anarkick Records hard techno label",
        }]},
    ])
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged={})
    assert isinstance(r, SocialsResult)
    assert r.instagram_tier == 1
    assert r.updates["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.tavily_credits == 1  # search only, no tier2/3 fallback needed


def test_tier2_extract_known_pages():
    http = _http_with([
        {"results": [{"url": "https://irrelevant.example", "raw_content": "nothing here"}]},
        {"results": [{
            "url": "https://www.anarkick.com",
            "raw_content": "follow https://www.instagram.com/anarkick_records",
        }]},
    ])
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    merged = {"website": "https://www.anarkick.com"}
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged=merged)
    assert r.instagram_tier == 2
    assert r.tavily_credits == 2  # search + extract
    assert r.updates["instagram_url"] == "https://www.instagram.com/anarkick_records"


def test_tier3_topup_with_validation():
    http = _http_with([
        {"results": []},  # tier1 search: nothing
        {"results": []},  # tier2 extract on known website: nothing
        {"results": [
            {"url": "https://www.instagram.com/ugra.music1111"},  # invalid, skipped
            {"url": "https://www.instagram.com/anarkick_records"},  # valid
        ]},
    ])
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    merged = {"website": "https://www.anarkick.com"}
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged=merged)
    assert r.instagram_tier == 3
    assert r.updates["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.tavily_credits == 3


def test_no_instagram_anywhere_leaves_updates_empty():
    http = _http_with([
        {"results": []},  # tier1: nothing
        {"results": [{"url": "https://www.instagram.com/totally.unrelated9"}]},  # tier3: no match
    ])
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    # no known official urls in merged -> tier2 skipped entirely
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged={})
    assert r.instagram_tier is None
    assert "instagram_url" not in r.updates
    assert r.tavily_credits == 2


# --- new: validation applied on tier 1/2 (task 4's precision fix) ---


def test_tier1_candidate_rejected_without_validation_match():
    http = _http_with([
        # tier1 search content: an unrelated instagram link surfaces in the results text
        {"results": [{
            "url": "https://blog.example/roundup",
            "content": "Some roundup post mentions instagram.com/totally_other_act",
            "raw_content": "",
        }]},
        # tier2 extract on the known website: nothing useful either
        {"results": [{"url": "https://www.anarkick.com", "raw_content": "no socials listed"}]},
        # tier3 targeted instagram search: the correct handle
        {"results": [{"url": "https://www.instagram.com/anarkick_records"}]},
    ])
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    merged = {"website": "https://www.anarkick.com"}
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged=merged)
    # the tier1 candidate must NOT be accepted as-is (would have been tier=1,
    # handle "totally_other_act", under the unvalidated splitlab behavior)
    assert r.instagram_tier == 3
    assert r.updates["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.tavily_credits == 3


# --- public API contract: no-op / never-raises / opportunistic other-socials ---


def test_noop_when_instagram_already_present():
    http = MagicMock()
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    merged = {"instagram_url": "https://www.instagram.com/existing"}
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged=merged)
    assert r.updates == {}
    assert r.instagram_tier is None
    assert r.tavily_credits == 0
    http.post.assert_not_called()


def test_never_raises_on_tavily_error():
    http = MagicMock()
    http.post.side_effect = RuntimeError("network down")
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged={})
    assert r.updates == {}
    assert r.instagram_tier is None
    assert r.error is not None and "network down" in r.error


def test_other_socials_applied_only_to_empty_merged_fields():
    http = _http_with([
        {"results": [{
            "url": "https://x.example",
            "content": "Anarkick Records hard techno label",
            "raw_content": (
                "Instagram: https://www.instagram.com/anarkick_records. "
                "Soundcloud: https://soundcloud.com/anarkickrecs. "
                "Bandcamp: https://anarkickrecs.bandcamp.com"
            ),
        }]},
    ])
    resolver = SocialsResolver(tavily_api_key="k", http=http)
    merged = {"soundcloud_url": "https://soundcloud.com/already-set"}
    r = resolver.resolve(kind="label", name="Anarkick Records", style="hard techno", merged=merged)
    assert r.updates["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.updates["bandcamp_url"] == "https://anarkickrecs.bandcamp.com"
    assert "soundcloud_url" not in r.updates  # merged already had a value


def test_credits_reported_when_a_later_tier_raises():
    """tier1 search succeeds (1 credit, no IG found), tier2 has no urls to extract,
    tier3 search raises -> resolve must not raise and must report credits spent so far"""
    call_count = [0]

    class FailOnSecondCall:
        def post(self, url, json):
            call_count[0] += 1
            if call_count[0] == 1:
                # tier1 search succeeds, no IG found
                class R:
                    def raise_for_status(self):
                        pass

                    def json(self):
                        return {"results": [{"url": "https://x.example", "raw_content": "nothing"}]}

                return R()
            else:
                # tier3 search fails
                raise RuntimeError("tavily down")

    resolver = SocialsResolver(tavily_api_key="key", http=FailOnSecondCall())
    r = resolver.resolve(kind="label", name="Nameless", style="dnb", merged={})
    assert r.error is not None
    assert r.tavily_credits >= 1
