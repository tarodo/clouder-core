"""auto label enrichment: source column, config + state tables

Revision ID: 20260525_25
Revises: 20260522_24
Create Date: 2026-05-25 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260525_25"
down_revision = "20260522_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_label_enrichment_runs",
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'manual'")),
    )

    op.create_table(
        "auto_enrich_config",
        sa.Column("kind", sa.Text, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("vendors", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("models", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("prompt_slug", sa.Text),
        sa.Column("prompt_version", sa.Text),
        sa.Column("merge_vendor", sa.Text),
        sa.Column("merge_model", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36)),
    )

    op.create_table(
        "label_auto_enrich_state",
        sa.Column(
            "label_id", sa.String(36),
            sa.ForeignKey("clouder_labels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "last_run_id", sa.String(36),
            sa.ForeignKey("clouder_label_enrichment_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("first_enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_label_auto_enrich_state_status",
        "label_auto_enrich_state",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_label_auto_enrich_state_status", table_name="label_auto_enrich_state")
    op.drop_table("label_auto_enrich_state")
    op.drop_table("auto_enrich_config")
    op.drop_column("clouder_label_enrichment_runs", "source")
