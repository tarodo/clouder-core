"""auto-ingest settings (one row) and per-period attempts

Revision ID: 20261007_34
Revises: 20261004_33
Create Date: 2026-10-07 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261007_34"
down_revision = "20261004_33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_ingest_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("mode", sa.Text, nullable=False, server_default=sa.text("'random'")),
        sa.Column(
            "fixed_times", JSONB, nullable=False,
            server_default=sa.text("'[\"09:00\", \"15:00\", \"21:00\"]'::jsonb"),
        ),
        sa.Column("runs_per_day", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("timezone", sa.Text, nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("periods_per_run", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("backfill_floor", sa.Date, nullable=False, server_default=sa.text("'2026-01-03'")),
        sa.Column("planned_runs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_run", JSONB),
        sa.Column("running_until", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by_user_id", sa.String(36)),
        sa.CheckConstraint("id = 1", name="ck_auto_ingest_settings_single_row"),
        sa.CheckConstraint("mode IN ('fixed', 'random')", name="ck_auto_ingest_settings_mode"),
    )
    op.execute("INSERT INTO auto_ingest_settings (id) VALUES (1)")

    op.create_table(
        "auto_ingest_attempts",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("style_id", sa.Integer, nullable=False),
        sa.Column("week_year", sa.Integer, nullable=False),
        sa.Column("week_number", sa.Integer, nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("run_id", sa.String(36)),
        sa.Column("error", sa.Text),
    )
    op.create_index(
        "ix_auto_ingest_attempts_pair",
        "auto_ingest_attempts",
        ["style_id", "week_year", "week_number", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_auto_ingest_attempts_pair", table_name="auto_ingest_attempts")
    op.drop_table("auto_ingest_attempts")
    op.drop_table("auto_ingest_settings")
