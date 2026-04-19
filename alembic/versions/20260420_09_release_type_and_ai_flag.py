"""add release_type and is_ai_suspected columns

Revision ID: 20260420_09
Revises: 20260419_08
Create Date: 2026-04-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260420_09"
down_revision = "20260419_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_tracks",
        sa.Column("release_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "clouder_tracks",
        sa.Column(
            "is_ai_suspected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "clouder_albums",
        sa.Column("release_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "clouder_labels",
        sa.Column(
            "is_ai_suspected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "clouder_artists",
        sa.Column(
            "is_ai_suspected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("clouder_artists", "is_ai_suspected")
    op.drop_column("clouder_labels", "is_ai_suspected")
    op.drop_column("clouder_albums", "release_type")
    op.drop_column("clouder_tracks", "is_ai_suspected")
    op.drop_column("clouder_tracks", "release_type")
