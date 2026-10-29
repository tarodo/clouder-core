"""Indexes for a label's / an artist's tracks

The player's label and artist cards count a label's tracks (albums by label_id, tracks by
album_id) and an artist's (track_artists by artist_id) on every track change; without these
each count scanned the whole table. The AI reputation recount reads the same joins.

Revision ID: 20261029_47
Revises: 20261029_46
Create Date: 2026-10-29 18:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20261029_47"
down_revision = "20261029_46"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_clouder_albums_label", "clouder_albums", "label_id"),
    ("ix_clouder_tracks_album", "clouder_tracks", "album_id"),
    ("ix_clouder_track_artists_artist", "clouder_track_artists", "artist_id"),
)


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _ in INDEXES:
        op.drop_index(name, table_name=table)
