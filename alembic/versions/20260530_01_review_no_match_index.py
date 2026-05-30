"""match_review_queue: partial unique index for no_match rows

Revision ID: 20260530_01
Revises: 20260527_27
Create Date: 2026-05-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260530_01"
down_revision = "20260527_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_review_no_match",
        "match_review_queue",
        ["clouder_track_id", "vendor"],
        unique=True,
        postgresql_where=sa.text("status = 'no_match'"),
    )


def downgrade() -> None:
    op.drop_index("uq_review_no_match", table_name="match_review_queue")
