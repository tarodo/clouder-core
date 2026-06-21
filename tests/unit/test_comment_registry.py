from __future__ import annotations

import pytest

from collector.comments.registry import (
    CommentPlatformDisabledError,
    get_comment_provider,
)
from collector.providers.youtube.comments import YouTubeCommentProvider


def test_returns_youtube_provider_when_enabled(monkeypatch):
    monkeypatch.setenv("COMMENT_PLATFORMS_ENABLED", "youtube")
    provider = get_comment_provider("youtube", api_key="K", session=object())
    assert isinstance(provider, YouTubeCommentProvider)
    assert provider.platform == "youtube"


def test_disabled_platform_raises(monkeypatch):
    monkeypatch.setenv("COMMENT_PLATFORMS_ENABLED", "")
    with pytest.raises(CommentPlatformDisabledError):
        get_comment_provider("youtube", api_key="K", session=object())


def test_unknown_platform_raises(monkeypatch):
    monkeypatch.setenv("COMMENT_PLATFORMS_ENABLED", "youtube,tiktok")
    with pytest.raises(CommentPlatformDisabledError):
        get_comment_provider("tiktok", api_key="K", session=object())
