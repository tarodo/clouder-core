"""user_tags.color becomes nullable

Revision ID: 20260511_18
Revises: 20260511_17
Create Date: 2026-05-11 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260511_18"
down_revision = "20260511_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_tags",
        "color",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    # Replace any nulls with a neutral sentinel before re-tightening the
    # constraint so the downgrade does not fail on a populated table.
    op.execute(
        "UPDATE user_tags SET color = '#888888' WHERE color IS NULL"
    )
    op.alter_column(
        "user_tags",
        "color",
        existing_type=sa.Text(),
        nullable=False,
    )
