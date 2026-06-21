"""comment_collections + external_comments

Revision ID: 20260621_31
Revises: 20260531_30
Create Date: 2026-06-21 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260621_31"
down_revision = "20260531_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("track_id", sa.String(36), sa.ForeignKey("clouder_tracks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("external_video_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("comment_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("track_id", "platform", name="uq_comment_collections_track_platform"),
        sa.CheckConstraint(
            "status IN ('pending', 'collected', 'empty', 'disabled', 'failed')",
            name="ck_comment_collections_status",
        ),
    )

    op.create_table(
        "external_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("comment_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("external_comment_id", sa.Text, nullable=False),
        sa.Column("author_name", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("author_avatar_url", sa.Text),
        sa.Column("text", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("like_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_id", "external_comment_id", name="uq_external_comments_collection_extid"),
    )
    op.create_index(
        "idx_external_comments_collection_rank",
        "external_comments",
        ["collection_id", "rank"],
    )


def downgrade() -> None:
    op.drop_index("idx_external_comments_collection_rank", table_name="external_comments")
    op.drop_table("external_comments")
    op.drop_table("comment_collections")
