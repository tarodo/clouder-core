"""add spotify_id and spotify_searched_at to clouder_tracks

Revision ID: 20260315_05
Revises: 20260314_04
Create Date: 2026-03-15 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260315_05"
down_revision = "20260314_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_tracks",
        sa.Column("spotify_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "clouder_tracks",
        sa.Column(
            "spotify_searched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_tracks_spotify_id",
        "clouder_tracks",
        ["spotify_id"],
        postgresql_where=sa.text("spotify_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_tracks_spotify_id", table_name="clouder_tracks")
    op.drop_column("clouder_tracks", "spotify_searched_at")
    op.drop_column("clouder_tracks", "spotify_id")
