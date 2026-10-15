"""AI badge index follows the badge analyzer: ai_detect -> ai_lofcz

The track-list badge now reads ai_lofcz (lofcz/ai-music-detector). ai_detect
(ArtifactNet) rows stay as a second opinion, so only the partial index moves.

Revision ID: 20261016_39
Revises: 20261015_38
Create Date: 2026-10-16 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_39"
down_revision = "20261015_38"
branch_labels = None
depends_on = None


def _badge_index(name: str, analyzer: str) -> None:
    op.create_index(
        name,
        "track_analyses",
        ["track_id"],
        postgresql_where=sa.text(
            f"analyzer = '{analyzer}' AND status = 'ok' AND (result->>'ai_detected')::boolean"
        ),
    )


def upgrade() -> None:
    _badge_index("ix_track_analyses_ai_lofcz_detected", "ai_lofcz")
    op.drop_index("ix_track_analyses_ai_detected", table_name="track_analyses")


def downgrade() -> None:
    _badge_index("ix_track_analyses_ai_detected", "ai_detect")
    op.drop_index("ix_track_analyses_ai_lofcz_detected", table_name="track_analyses")
