"""track YouTube search state on clouder_tracks

The YouTube search worker stamps youtube_searched_at the way the Spotify
worker stamps spotify_searched_at: claim, done, release. The partial index
serves the sweep's "not searched yet, newest first" lookup.

Revision ID: 20261014_37
Revises: 20261010_36
Create Date: 2026-10-14 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261014_37"
down_revision = "20261010_36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_tracks",
        sa.Column("youtube_searched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_clouder_tracks_youtube_unsearched",
        "clouder_tracks",
        [sa.text("created_at DESC")],
        postgresql_where=sa.text("youtube_searched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_clouder_tracks_youtube_unsearched", table_name="clouder_tracks")
    op.drop_column("clouder_tracks", "youtube_searched_at")
