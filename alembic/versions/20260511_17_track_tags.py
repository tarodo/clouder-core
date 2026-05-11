"""user_tags and track_tags

Revision ID: 20260511_17
Revises: 20260509_16
Create Date: 2026-05-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260511_17"
down_revision = "20260509_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_tags_user",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_user_tags_user_normalized_name",
        ),
    )
    op.create_index("idx_user_tags_user_id", "user_tags", ["user_id"])

    op.create_table(
        "track_tags",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "track_id", "tag_id"),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["clouder_tracks.id"],
            name="fk_track_tags_track",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["user_tags.id"],
            name="fk_track_tags_tag",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_track_tags_user",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_track_tags_user_tag", "track_tags", ["user_id", "tag_id"]
    )
    op.create_index(
        "idx_track_tags_user_track", "track_tags", ["user_id", "track_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_track_tags_user_track", table_name="track_tags")
    op.drop_index("idx_track_tags_user_tag", table_name="track_tags")
    op.drop_table("track_tags")
    op.drop_index("idx_user_tags_user_id", table_name="user_tags")
    op.drop_table("user_tags")
