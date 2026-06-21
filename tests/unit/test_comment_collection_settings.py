from __future__ import annotations

from collector.settings import (
    get_comment_collection_worker_settings,
    reset_settings_cache,
)


def test_youtube_api_key_resolved_from_env(monkeypatch):
    reset_settings_cache()
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key-123")
    s = get_comment_collection_worker_settings()
    assert s.youtube_api_key == "yt-key-123"
    reset_settings_cache()


def test_youtube_api_key_defaults_empty(monkeypatch):
    reset_settings_cache()
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY_SSM_PARAMETER", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY_SECRET_ARN", raising=False)
    s = get_comment_collection_worker_settings()
    assert s.youtube_api_key == ""
    reset_settings_cache()
