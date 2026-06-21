"""SQS message contract for the comment-collection worker."""

from __future__ import annotations

from pydantic import BaseModel


class CommentCollectMessage(BaseModel):
    track_id: str
    platform: str
    video_id: str
    collection_id: str
