"""user label preferences

Revision ID: 20260519_23
Revises: 20260518_22
Create Date: 2026-05-19 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260519_23"
down_revision = "20260518_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_user_label_prefs",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("label_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "label_id", name="pk_user_label_prefs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_user_label_prefs_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["label_id"], ["clouder_labels.id"],
            name="fk_user_label_prefs_label",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('liked', 'disliked')",
            name="ck_user_label_prefs_status",
        ),
    )
    op.create_index(
        "idx_user_label_prefs_user_status",
        "clouder_user_label_prefs",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_label_prefs_user_status",
        table_name="clouder_user_label_prefs",
    )
    op.drop_table("clouder_user_label_prefs")
