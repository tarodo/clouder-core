"""add label enrichment tables (runs, cells, label_info)

Revision ID: 20260518_22
Revises: 20260518_21
Create Date: 2026-05-18 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "20260518_22"
down_revision = "20260518_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_label_enrichment_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("vendors", JSONB, nullable=False),
        sa.Column("models", JSONB, nullable=False),
        sa.Column("merge_vendor", sa.Text, nullable=False),
        sa.Column("merge_model", sa.Text, nullable=False),
        sa.Column("requested_labels", sa.Integer, nullable=False),
        sa.Column("cells_total", sa.Integer, nullable=False),
        sa.Column("cells_ok", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cells_error", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by_user_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "idx_label_enr_runs_created_at",
        "clouder_label_enrichment_runs",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_label_enrichment_cells",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("clouder_label_enrichment_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "label_id",
            sa.String(36),
            sa.ForeignKey("clouder_labels.id"),
            nullable=False,
        ),
        sa.Column("vendor", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("parsed", JSONB),
        sa.Column("citations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("usage", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "label_id", "vendor", name="uq_label_enr_cell"),
    )
    op.create_index(
        "idx_label_enr_cells_label",
        "clouder_label_enrichment_cells",
        ["label_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_label_info",
        sa.Column(
            "label_id",
            sa.String(36),
            sa.ForeignKey("clouder_labels.id"),
            primary_key=True,
        ),
        sa.Column(
            "last_run_id",
            sa.String(36),
            sa.ForeignKey("clouder_label_enrichment_runs.id"),
            nullable=False,
        ),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("merged", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("ai_content", sa.Text, nullable=False),
        sa.Column("ai_confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "primary_styles",
            ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("tagline", sa.Text),
        sa.Column("country", sa.Text),
        sa.Column("founded_year", sa.Integer),
        sa.Column("activity", sa.Text),
        sa.Column("last_release_date", sa.Date),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_label_info_updated_at",
        "clouder_label_info",
        [sa.text("updated_at DESC")],
    )
    op.create_index("idx_label_info_status", "clouder_label_info", ["status"])
    op.create_index(
        "idx_label_info_primary_styles",
        "clouder_label_info",
        ["primary_styles"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_label_info_primary_styles", table_name="clouder_label_info")
    op.drop_index("idx_label_info_status", table_name="clouder_label_info")
    op.drop_index("idx_label_info_updated_at", table_name="clouder_label_info")
    op.drop_table("clouder_label_info")

    op.drop_index("idx_label_enr_cells_label", table_name="clouder_label_enrichment_cells")
    op.drop_table("clouder_label_enrichment_cells")

    op.drop_index("idx_label_enr_runs_created_at", table_name="clouder_label_enrichment_runs")
    op.drop_table("clouder_label_enrichment_runs")
