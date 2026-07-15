from splitlab.social_regex import (
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
