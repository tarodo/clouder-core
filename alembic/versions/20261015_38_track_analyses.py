"""track_analyses: results of the external audio analyzer

One row per (track, analyzer). The analyzer leases rows (status 'leased' with
lease_id / leased_until), then posts a result (ok / failed / unusable_source).
analysis_service_state keeps the worker's heartbeat for the admin card.

Revision ID: 20261015_38
Revises: 20261014_37
Create Date: 2026-10-15 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "20261015_38"
down_revision = "20261014_37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "track_analyses",
        sa.Column(
            "track_id",
            sa.String(36),
            sa.ForeignKey("clouder_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analyzer", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("audio_sha256", sa.CHAR(64), nullable=True),
        sa.Column("video_id", sa.String(32), nullable=True),
        sa.Column("lease_id", UUID(as_uuid=False), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("track_id", "analyzer", name="pk_track_analyses"),
        sa.CheckConstraint(
            "status IN ('leased', 'ok', 'failed', 'unusable_source')",
            name="ck_track_analyses_status",
        ),
    )
    # The badge lookup in the track lists: ok, AI-flagged tracks.
    op.create_index(
        "ix_track_analyses_ai_detected",
        "track_analyses",
        ["track_id"],
        postgresql_where=sa.text(
            "analyzer = 'ai_detect' AND status = 'ok' AND (result->>'ai_detected')::boolean"
        ),
    )
    op.create_index(
        "ix_track_analyses_analyzer_status", "track_analyses", ["analyzer", "status"]
    )
    op.create_table(
        "analysis_service_state",
        sa.Column("service", sa.String(32), primary_key=True),
        sa.Column("last_claim_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "claim_analyzers",
            ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )


def downgrade() -> None:
    op.drop_table("analysis_service_state")
    op.drop_index("ix_track_analyses_analyzer_status", table_name="track_analyses")
    op.drop_index("ix_track_analyses_ai_detected", table_name="track_analyses")
    op.drop_table("track_analyses")
