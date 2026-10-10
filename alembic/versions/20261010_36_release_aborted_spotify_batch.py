"""hand back the tracks a deadline-cut Spotify batch left stamped as searched

On 2026-10-10 a paced 2000-track batch, claimed at 13:56:57-13:57:01 UTC,
searched 1,055 tracks before the Lambda deadline. The other 945 kept the
claim stamp and looked "searched, not found". The worker now releases them
itself (spotify_handler); this data fix releases the ones already stranded,
so the next search picks them up.

Revision ID: 20261010_36
Revises: 20261010_35
Create Date: 2026-10-10 00:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20261010_36"
down_revision = "20261010_35"
branch_labels = None
depends_on = None

RELEASE_SQL = """
UPDATE clouder_tracks
SET spotify_searched_at = NULL, updated_at = now()
WHERE spotify_id IS NULL
  AND spotify_searched_at >= TIMESTAMPTZ '2026-10-10 13:56:56+00'
  AND spotify_searched_at <  TIMESTAMPTZ '2026-10-10 13:57:02+00'
"""


def upgrade() -> None:
    op.execute(RELEASE_SQL)


def downgrade() -> None:
    pass  # a data fix: the released rows are simply searched again
