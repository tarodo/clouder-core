"""YouTube search claims newest release first: index the unsearched rows by publish date

The sweep now walks the whole catalog by release date (newest first) instead of
by ingest time, so the partial index over unsearched rows follows that order.

Revision ID: 20261022_42
Revises: 20261021_41
Create Date: 2026-10-22 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261022_42"
down_revision = "20261021_41"
branch_labels = None
depends_on = None

_UNSEARCHED = sa.text("youtube_searched_at IS NULL")


def upgrade() -> None:
    op.drop_index("ix_clouder_tracks_youtube_unsearched", table_name="clouder_tracks")
    op.create_index(
        "ix_clouder_tracks_youtube_unsearched",
        "clouder_tracks",
        [sa.text("publish_date DESC NULLS LAST"), sa.text("created_at DESC"), "id"],
        postgresql_where=_UNSEARCHED,
    )


def downgrade() -> None:
    op.drop_index("ix_clouder_tracks_youtube_unsearched", table_name="clouder_tracks")
    op.create_index(
        "ix_clouder_tracks_youtube_unsearched",
        "clouder_tracks",
        [sa.text("created_at DESC")],
        postgresql_where=_UNSEARCHED,
    )
