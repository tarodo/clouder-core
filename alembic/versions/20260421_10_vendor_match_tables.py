"""vendor_track_map + match_review_queue

Revision ID: 20260421_10
Revises: 20260420_09
Create Date: 2026-04-21 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260421_10"
down_revision = "20260420_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_track_map",
        sa.Column("clouder_track_id", sa.String(length=36), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("vendor_track_id", sa.String(length=128), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["clouder_track_id"], ["clouder_tracks.id"]),
        sa.PrimaryKeyConstraint(
            "clouder_track_id", "vendor", name="pk_vendor_track_map"
        ),
    )
    op.create_index(
        "idx_vtm_vendor_track",
        "vendor_track_map",
        ["vendor", "clouder_track_id"],
    )

    op.create_table(
        "match_review_queue",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clouder_track_id", sa.String(length=36), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("candidates", JSONB(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["clouder_track_id"], ["clouder_tracks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_review_pending",
        "match_review_queue",
        ["clouder_track_id", "vendor"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_review_pending", table_name="match_review_queue")
    op.drop_table("match_review_queue")
    op.drop_index("idx_vtm_vendor_track", table_name="vendor_track_map")
    op.drop_table("vendor_track_map")
