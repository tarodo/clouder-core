"""triage suggestions: audio_features, ml_models, track_predictions

audio_features marks which YouTube videos have a light-1 profile in S3. ml_models is
one row per (user, style); version 0 means requested, never trained. track_predictions
holds the scores of the current model version.

Revision ID: 20261023_45
Revises: 20261023_44
Create Date: 2026-10-23 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261023_45"
down_revision = "20261023_44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audio_features",
        sa.Column("video_id", sa.String(32), primary_key=True),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("audio_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ml_models",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "style_id",
            sa.String(36),
            sa.ForeignKey("clouder_styles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrain_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("n_labels", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("n_keep", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("keep_threshold", sa.REAL(), nullable=True),
        sa.Column("classes", postgresql.JSONB(), nullable=True),
        sa.Column(
            "metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("artifact_key", sa.Text(), nullable=True),
    )
    op.create_table(
        "track_predictions",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("style_id", sa.String(36), primary_key=True),
        sa.Column(
            "track_id",
            sa.String(36),
            sa.ForeignKey("clouder_tracks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_version", sa.Integer(), nullable=False),
        sa.Column("keep_score", sa.REAL(), nullable=True),
        sa.Column("keep", sa.Boolean(), nullable=True),
        sa.Column("categories", postgresql.JSONB(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("track_predictions")
    op.drop_table("ml_models")
    op.drop_table("audio_features")
