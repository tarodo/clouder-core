"""playlists: per-user YouTube Music publish state

Revision ID: 20260531_29
Revises: 20260530_28
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260531_29"
down_revision = "20260530_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playlists",
        sa.Column("ytmusic_playlist_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "playlists",
        sa.Column(
            "ytmusic_last_published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "playlists",
        sa.Column(
            "ytmusic_needs_republish",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "idx_playlists_ytmusic_playlist_id",
        "playlists",
        ["ytmusic_playlist_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_playlists_ytmusic_playlist_id", table_name="playlists"
    )
    op.drop_column("playlists", "ytmusic_needs_republish")
    op.drop_column("playlists", "ytmusic_last_published_at")
    op.drop_column("playlists", "ytmusic_playlist_id")
