"""make last_run_id nullable in source_entities for non-Beatport sources (e.g. Spotify)

Revision ID: 20260315_06
Revises: 20260315_05
Create Date: 2026-03-15 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260315_06"
down_revision = "20260315_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "source_entities",
        "last_run_id",
        existing_type=sa.String(36),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE source_entities SET last_run_id = 'unknown' WHERE last_run_id IS NULL")
    op.alter_column(
        "source_entities",
        "last_run_id",
        existing_type=sa.String(36),
        nullable=False,
    )
