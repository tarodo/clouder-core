"""AI flag index serves the pair verdict: ai_lofcz + ai_deezer

The track-list verdict reads both ai_lofcz and ai_deezer, and the admin status
counts tracks per verdict, so the lofcz-only partial index becomes one over every
ok AI-flagged row, keyed by (track_id, analyzer).

Revision ID: 20261016_40
Revises: 20261016_39
Create Date: 2026-10-16 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261016_40"
down_revision = "20261016_39"
branch_labels = None
depends_on = None

_FLAGGED = "status = 'ok' AND (result->>'ai_detected')::boolean"


def upgrade() -> None:
    op.create_index(
        "ix_track_analyses_ai_flag",
        "track_analyses",
        ["track_id", "analyzer"],
        postgresql_where=sa.text(_FLAGGED),
    )
    op.drop_index("ix_track_analyses_ai_lofcz_detected", table_name="track_analyses")


def downgrade() -> None:
    op.create_index(
        "ix_track_analyses_ai_lofcz_detected",
        "track_analyses",
        ["track_id"],
        postgresql_where=sa.text(f"analyzer = 'ai_lofcz' AND {_FLAGGED}"),
    )
    op.drop_index("ix_track_analyses_ai_flag", table_name="track_analyses")
