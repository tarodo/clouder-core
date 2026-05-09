"""ingest_runs: add Saturday-week + period columns for admin ingest

Revision ID: 20260509_16
Revises: 20260428_15
Create Date: 2026-05-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260509_16"
down_revision = "20260428_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("ingest_runs", "iso_year", nullable=True)
    op.alter_column("ingest_runs", "iso_week", nullable=True)
    op.add_column("ingest_runs", sa.Column("week_year", sa.Integer(), nullable=True))
    op.add_column("ingest_runs", sa.Column("week_number", sa.Integer(), nullable=True))
    op.add_column("ingest_runs", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("ingest_runs", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column(
        "ingest_runs",
        sa.Column(
            "is_custom_range",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "idx_ingest_runs_coverage",
        "ingest_runs",
        ["week_year", "style_id", "week_number"],
    )


def downgrade() -> None:
    op.drop_index("idx_ingest_runs_coverage", table_name="ingest_runs")
    op.drop_column("ingest_runs", "is_custom_range")
    op.drop_column("ingest_runs", "period_end")
    op.drop_column("ingest_runs", "period_start")
    op.drop_column("ingest_runs", "week_number")
    op.drop_column("ingest_runs", "week_year")
    op.alter_column("ingest_runs", "iso_week", nullable=False)
    op.alter_column("ingest_runs", "iso_year", nullable=False)
