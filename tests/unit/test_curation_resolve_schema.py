import pytest
from pydantic import ValidationError

from collector.curation.schemas import ResolveMatchIn, YT_VIDEO_ID_RE


def test_accept_requires_valid_video_id():
    m = ResolveMatchIn.model_validate(
        {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "dQw4w9WgXcQ"}
    )
    assert m.action == "accept"
    assert m.vendor_track_id == "dQw4w9WgXcQ"


def test_accept_rejects_bad_video_id():
    with pytest.raises(ValidationError):
        ResolveMatchIn.model_validate(
            {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "too-short"}
        )


def test_accept_requires_video_id_present():
    with pytest.raises(ValidationError):
        ResolveMatchIn.model_validate({"vendor": "ytmusic", "action": "accept"})


def test_reject_needs_no_video_id():
    m = ResolveMatchIn.model_validate({"vendor": "ytmusic", "action": "reject"})
    assert m.action == "reject"
    assert m.vendor_track_id is None


def test_regex_matches_11_char_id():
    assert YT_VIDEO_ID_RE.match("dQw4w9WgXcQ")
    assert not YT_VIDEO_ID_RE.match("dQw4w9WgXc")  # 10 chars
