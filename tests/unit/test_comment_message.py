from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.comments.messages import CommentCollectMessage


def test_roundtrip_json():
    msg = CommentCollectMessage(
        track_id="t1", platform="youtube", video_id="vidA", collection_id="col1"
    )
    raw = msg.model_dump_json()
    again = CommentCollectMessage.model_validate_json(raw)
    assert again.track_id == "t1"
    assert again.platform == "youtube"
    assert again.video_id == "vidA"
    assert again.collection_id == "col1"


def test_missing_field_rejected():
    with pytest.raises(ValidationError):
        CommentCollectMessage.model_validate({"track_id": "t1", "platform": "youtube"})


def test_video_id_defaults_to_empty_when_omitted():
    msg = CommentCollectMessage.model_validate_json(
        '{"track_id": "t1", "platform": "youtube", "collection_id": "col1"}'
    )
    assert msg.video_id == ""


def test_video_id_still_parses_when_present():
    msg = CommentCollectMessage.model_validate_json(
        '{"track_id": "t1", "platform": "youtube", "video_id": "vidA", "collection_id": "col1"}'
    )
    assert msg.video_id == "vidA"
