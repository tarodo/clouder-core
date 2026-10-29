"""AI reputation of labels and artists; AI levels a triage block sends to NOT

clouder_labels / clouder_artists count their tracks (ai_total), the ones a detector checked
(ai_checked: an ok ai_lofcz or ai_deezer row) and the flagged ones (ai_tracks). ai_level is
generated from the share of checked: 1 = at least one, 2 = 25-50%, 3 = over half. The
collector recounts as detector results land; this migration backfills.

triage_blocks.ai_labels_min_level / ai_artists_min_level: the level from which a block's
creation sends a label's / an artist's tracks to NOT; NULL = off.

Revision ID: 20261029_46
Revises: 20261023_45
Create Date: 2026-10-29 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261029_46"
down_revision = "20261023_45"
branch_labels = None
depends_on = None

LEVEL = (
    "CASE WHEN ai_tracks = 0 THEN NULL WHEN ai_tracks * 2 > ai_checked THEN 3"
    " WHEN ai_tracks * 4 >= ai_checked THEN 2 ELSE 1 END"
)

# Per track: checked / flagged by the AI detector pair (no rows -> NULL -> neither).
_PER_TRACK = """
    CROSS JOIN LATERAL (
        SELECT bool_or(ta.status = 'ok') AS checked,
               bool_or(ta.status = 'ok' AND (ta.result->>'ai_detected')::boolean) AS ai
        FROM track_analyses ta
        WHERE ta.track_id = t.id AND ta.analyzer IN ('ai_lofcz', 'ai_deezer')
    ) x"""

BACKFILL_LABELS = f"""
UPDATE clouder_labels l
SET ai_total = c.total, ai_checked = c.checked, ai_tracks = c.ai
FROM (
    SELECT a.label_id, count(*) AS total, count(*) FILTER (WHERE x.checked) AS checked,
           count(*) FILTER (WHERE x.ai) AS ai
    FROM clouder_albums a
    JOIN clouder_tracks t ON t.album_id = a.id
    {_PER_TRACK}
    WHERE a.label_id IS NOT NULL
    GROUP BY a.label_id
) c
WHERE l.id = c.label_id
"""

# An artist credited twice on one track (main + remixer) counts it once.
BACKFILL_ARTISTS = f"""
UPDATE clouder_artists ar
SET ai_total = c.total, ai_checked = c.checked, ai_tracks = c.ai
FROM (
    SELECT p.artist_id, count(*) AS total, count(*) FILTER (WHERE x.checked) AS checked,
           count(*) FILTER (WHERE x.ai) AS ai
    FROM (SELECT DISTINCT artist_id, track_id FROM clouder_track_artists) p
    JOIN clouder_tracks t ON t.id = p.track_id
    {_PER_TRACK}
    GROUP BY p.artist_id
) c
WHERE ar.id = c.artist_id
"""


def upgrade() -> None:
    for table in ("clouder_labels", "clouder_artists"):
        for column in ("ai_total", "ai_checked", "ai_tracks"):
            op.add_column(
                table,
                sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text("0")),
            )
        op.add_column(
            table, sa.Column("ai_level", sa.SmallInteger(), sa.Computed(LEVEL, persisted=True))
        )
    for column in ("ai_labels_min_level", "ai_artists_min_level"):
        op.add_column("triage_blocks", sa.Column(column, sa.SmallInteger(), nullable=True))
        op.create_check_constraint(
            f"ck_triage_blocks_{column}", "triage_blocks", f"{column} BETWEEN 1 AND 3"
        )
    op.execute(BACKFILL_LABELS)
    op.execute(BACKFILL_ARTISTS)


def downgrade() -> None:
    for column in ("ai_labels_min_level", "ai_artists_min_level"):
        op.drop_constraint(f"ck_triage_blocks_{column}", "triage_blocks", type_="check")
        op.drop_column("triage_blocks", column)
    for table in ("clouder_labels", "clouder_artists"):
        for column in ("ai_level", "ai_tracks", "ai_checked", "ai_total"):
            op.drop_column(table, column)
