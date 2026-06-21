"""Unit tests for the comment-provider Protocol surface and shared type."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector.providers.base import CollectedComment, CommentProvider


def test_collected_comment_is_frozen() -> None:
    c = CollectedComment(
        external_id="c1",
        author_name="Foo",
        author_avatar_url=None,
        text="hi",
        like_count=3,
        published_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        rank=0,
    )
    assert c.external_id == "c1"
    assert c.rank == 0
    with pytest.raises(Exception):
        c.text = "other"  # frozen dataclass


def test_comment_provider_is_runtime_checkable() -> None:
    assert not isinstance(object(), CommentProvider)

    class Dummy:
        platform = "youtube"

        def collect(self, video_ref, *, limit=100):
            return []

    assert isinstance(Dummy(), CommentProvider)
