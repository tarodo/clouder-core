"""add artist enrichment tables (runs, cells, artist_info, auto state, prefs)

Revision ID: 20260527_26
Revises: 20260525_25
Create Date: 2026-05-27 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "20260527_26"
down_revision = "20260525_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_artist_enrichment_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("vendors", JSONB, nullable=False),
        sa.Column("models", JSONB, nullable=False),
        sa.Column("merge_vendor", sa.Text, nullable=False),
        sa.Column("merge_model", sa.Text, nullable=False),
        sa.Column("requested_artists", sa.Integer, nullable=False),
        sa.Column("cells_total", sa.Integer, nullable=False),
        sa.Column("cells_ok", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cells_error", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by_user_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'manual'")),
    )
    op.create_index(
        "idx_artist_enr_runs_created_at",
        "clouder_artist_enrichment_runs",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_artist_enrichment_cells",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("clouder_artist_enrichment_runs.id"), nullable=False),
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id"), nullable=False),
        sa.Column("vendor", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("parsed", JSONB),
        sa.Column("citations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("usage", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "artist_id", "vendor", name="uq_artist_enr_cell"),
    )
    op.create_index(
        "idx_artist_enr_cells_artist",
        "clouder_artist_enrichment_cells",
        ["artist_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "clouder_artist_info",
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id"), primary_key=True),
        sa.Column("last_run_id", sa.String(36), sa.ForeignKey("clouder_artist_enrichment_runs.id"), nullable=False),
        sa.Column("prompt_slug", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("merged", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("ai_content", sa.Text, nullable=False),
        sa.Column("ai_confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("primary_styles", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("artist_type", sa.Text),
        sa.Column("country", sa.Text),
        sa.Column("active_since", sa.Integer),
        sa.Column("tagline", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_artist_info_updated_at", "clouder_artist_info", [sa.text("updated_at DESC")])
    op.create_index("idx_artist_info_status", "clouder_artist_info", ["status"])
    op.create_index(
        "idx_artist_info_primary_styles",
        "clouder_artist_info",
        ["primary_styles"],
        postgresql_using="gin",
    )

    op.create_table(
        "artist_auto_enrich_state",
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("last_run_id", sa.String(36), sa.ForeignKey("clouder_artist_enrichment_runs.id", ondelete="SET NULL")),
        sa.Column("first_enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artist_auto_enrich_state_status", "artist_auto_enrich_state", ["status"])

    op.create_table(
        "clouder_user_artist_prefs",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("artist_id", sa.String(36), sa.ForeignKey("clouder_artists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "artist_id", name="pk_user_artist_prefs"),
    )


def downgrade() -> None:
    op.drop_table("clouder_user_artist_prefs")
    op.drop_index("ix_artist_auto_enrich_state_status", table_name="artist_auto_enrich_state")
    op.drop_table("artist_auto_enrich_state")
    op.drop_index("idx_artist_info_primary_styles", table_name="clouder_artist_info")
    op.drop_index("idx_artist_info_status", table_name="clouder_artist_info")
    op.drop_index("idx_artist_info_updated_at", table_name="clouder_artist_info")
    op.drop_table("clouder_artist_info")
    op.drop_index("idx_artist_enr_cells_artist", table_name="clouder_artist_enrichment_cells")
    op.drop_table("clouder_artist_enrichment_cells")
    op.drop_index("idx_artist_enr_runs_created_at", table_name="clouder_artist_enrichment_runs")
    op.drop_table("clouder_artist_enrichment_runs")
