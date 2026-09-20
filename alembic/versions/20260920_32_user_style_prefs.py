"""user style selection

Revision ID: 20260920_32
Revises: 20260621_31
Create Date: 2026-09-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260920_32"
down_revision = "20260621_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_user_style_prefs",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("style_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "style_id", name="pk_user_style_prefs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_user_style_prefs_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["style_id"], ["clouder_styles.id"],
            name="fk_user_style_prefs_style",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_user_style_prefs_position_nonneg"
        ),
    )
    op.create_index(
        "idx_user_style_prefs_user_position",
        "clouder_user_style_prefs",
        ["user_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_style_prefs_user_position",
        table_name="clouder_user_style_prefs",
    )
    op.drop_table("clouder_user_style_prefs")
