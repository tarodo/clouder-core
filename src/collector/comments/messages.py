"""SQS message contract for the comment-collection worker."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CommentCollectMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    track_id: str
    platform: str
    video_id: str
    collection_id: str
