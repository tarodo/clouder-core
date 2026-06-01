"""add key_name and key_camelot to clouder_tracks + backfill from beatport payload

Revision ID: 20260531_30
Revises: 20260531_29
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260531_30"
down_revision = "20260531_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_tracks",
        sa.Column("key_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "clouder_tracks",
        sa.Column("key_camelot", sa.String(8), nullable=True),
    )
    # Backfill from the raw Beatport payload already persisted in
    # source_entities.payload (JSONB). Join clouder_tracks -> identity_map ->
    # source_entities by the (source, entity_type, external_id) triple.
    # key_camelot is NULL when either camelot half is absent (|| of a NULL
    # operand yields NULL). updated_at is intentionally left untouched.
    op.execute(
        """
        UPDATE clouder_tracks ct
        SET key_name = se.payload->'key'->>'name',
            key_camelot = (se.payload->'key'->>'camelot_number')
                          || (se.payload->'key'->>'camelot_letter')
        FROM source_entities se
        JOIN identity_map im
          ON im.source = se.source
         AND im.entity_type = se.entity_type
         AND im.external_id = se.external_id
        WHERE se.source = 'beatport'
          AND se.entity_type = 'track'
          AND im.clouder_entity_type = 'track'
          AND im.clouder_id = ct.id
          AND jsonb_typeof(se.payload->'key') = 'object'
        """
    )


def downgrade() -> None:
    op.drop_column("clouder_tracks", "key_camelot")
    op.drop_column("clouder_tracks", "key_name")
