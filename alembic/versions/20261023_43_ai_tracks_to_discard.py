"""AI-flagged tracks leave play: open blocks and categories send them to DISCARD (one-off)

The owner's rule (2026-10-23): a track either detector flags (ai_lofcz or ai_deezer, any badge
level) goes to DISCARD. New blocks and fresh results apply it in code; this migration applies it
once to what is already there:
- in every open block the track moves to that block's DISCARD bucket from any other bucket;
- kept in a category, it leaves the category for the DISCARD bucket of the block it came from
  (nowhere when it was added by hand), and that user's tags on it go with the membership.
Finalized blocks and playlists are not touched. The SQL is a snapshot of
collector.repositories.analysis._DISCARD_AI over every flagged track; downgrade cannot restore the
removed category rows (the upgrade prints how many it moved).

Revision ID: 20261023_43
Revises: 20261022_42
Create Date: 2026-10-23 06:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_43"
down_revision = "20261022_42"
branch_labels = None
depends_on = None

_DISCARD = """
WITH flagged AS (
    SELECT DISTINCT track_id AS id FROM track_analyses
    WHERE analyzer IN ('ai_lofcz', 'ai_deezer') AND status = 'ok'
      AND (result->>'ai_detected')::boolean
), open_rows AS (
    SELECT x.triage_bucket_id, x.track_id, d.id AS discard_id
    FROM triage_bucket_tracks x
    JOIN flagged f ON f.id = x.track_id
    JOIN triage_buckets b ON b.id = x.triage_bucket_id AND b.bucket_type <> 'DISCARD'
    JOIN triage_blocks tb ON tb.id = b.triage_block_id
     AND tb.status = 'IN_PROGRESS' AND tb.deleted_at IS NULL
    JOIN triage_buckets d ON d.triage_block_id = tb.id AND d.bucket_type = 'DISCARD'
), unbucketed AS (
    DELETE FROM triage_bucket_tracks x USING open_rows o
    WHERE x.triage_bucket_id = o.triage_bucket_id AND x.track_id = o.track_id
    RETURNING o.discard_id, x.track_id
), uncategorized AS (
    DELETE FROM category_tracks ct USING flagged f WHERE ct.track_id = f.id
    RETURNING ct.track_id, ct.source_triage_block_id
), discarded AS (
    INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)
    SELECT s.discard_id, s.track_id, now() FROM (
        SELECT discard_id, track_id FROM unbucketed
        UNION
        SELECT d.id, u.track_id FROM uncategorized u
        JOIN triage_buckets d
          ON d.triage_block_id = u.source_triage_block_id AND d.bucket_type = 'DISCARD'
    ) s
    ON CONFLICT (triage_bucket_id, track_id) DO NOTHING
    RETURNING 1
)
SELECT (SELECT count(*) FROM unbucketed) AS moved,
       (SELECT array_agg(DISTINCT track_id) FROM uncategorized) AS uncategorized
"""

# After the statement above: a track that just left a category loses the tags of every user no
# alive category of whom still holds it (TagsRepository.cleanup_orphaned_track_tags).
_UNTAG = """
DELETE FROM track_tags tt
WHERE tt.track_id = ANY(:ids)
  AND NOT EXISTS (
      SELECT 1 FROM category_tracks ct JOIN categories c ON c.id = ct.category_id
      WHERE ct.track_id = tt.track_id AND c.user_id = tt.user_id AND c.deleted_at IS NULL)
"""


def upgrade() -> None:
    bind = op.get_bind()
    moved, left = bind.execute(sa.text(_DISCARD)).one()
    untagged = bind.execute(sa.text(_UNTAG), {"ids": left}).rowcount if left else 0
    print(
        f"ai tracks to DISCARD: moved {moved}, uncategorized {len(left or [])}, untagged {untagged}"
    )


def downgrade() -> None:
    # The removed category rows are not kept anywhere: nothing to restore.
    pass
