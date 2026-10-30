"""audio_waveforms: the player's waveform, one per video

The analyzer posts one for every video it analyzes (new tracks; tracks without one can be
handed out again later by claiming the `waveform` analyzer). `data` is base64 of 3 bands x
600 bins of u8 dB; `duration_ms` is the decoded length, so the player draws the waveform
only over a Spotify track of the same length (within 3 s).

Revision ID: 20261029_48
Revises: 20261029_47
Create Date: 2026-10-29 22:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261029_48"
down_revision = "20261029_47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audio_waveforms",
        sa.Column("video_id", sa.String(32), primary_key=True),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("audio_sha256", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("data", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audio_waveforms")
