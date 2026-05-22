"""triage populate options

Revision ID: 20260522_24
Revises: 20260519_23
Create Date: 2026-05-22 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260522_24"
down_revision = "20260519_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "triage_blocks",
        sa.Column(
            "old_offset_weeks",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "triage_blocks",
        sa.Column(
            "include_disliked_labels",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.create_check_constraint(
        "ck_triage_blocks_old_offset_weeks_nonneg",
        "triage_blocks",
        "old_offset_weeks >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_triage_blocks_old_offset_weeks_nonneg",
        "triage_blocks",
        type_="check",
    )
    op.drop_column("triage_blocks", "include_disliked_labels")
    op.drop_column("triage_blocks", "old_offset_weeks")
