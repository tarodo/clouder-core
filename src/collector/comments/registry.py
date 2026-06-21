"""Comment-provider registry, keyed by platform.

Separate from providers.registry (which is keyed by export vendor). Adding a
new platform = one builder entry. Gated by COMMENT_PLATFORMS_ENABLED
(comma-separated, e.g. "youtube").
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from ..providers.base import CommentProvider


class CommentPlatformDisabledError(Exception):
    def __init__(self, platform: str) -> None:
        super().__init__(f"comment platform disabled or unknown: {platform}")
        self.platform = platform


def _build_youtube(*, api_key: str, session: Any) -> CommentProvider:
    from ..providers.youtube.comments import YouTubeCommentProvider

    return YouTubeCommentProvider(api_key=api_key, session=session)


_BUILDERS: dict[str, Callable[..., CommentProvider]] = {
    "youtube": _build_youtube,
}


def _enabled_platforms() -> set[str]:
    raw = os.environ.get("COMMENT_PLATFORMS_ENABLED", "youtube").strip()
    return {p.strip() for p in raw.split(",") if p.strip()}


def get_comment_provider(platform: str, *, api_key: str, session: Any) -> CommentProvider:
    if platform not in _enabled_platforms():
        raise CommentPlatformDisabledError(platform)
    builder = _BUILDERS.get(platform)
    if builder is None:
        raise CommentPlatformDisabledError(platform)
    return builder(api_key=api_key, session=session)
