"""add source_relations index

Revision ID: 20260308_02
Revises: 20260301_01
Create Date: 2026-03-08 00:00:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260308_02"
down_revision = "20260301_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_source_relations_from",
        "source_relations",
        ["source", "from_entity_type", "from_external_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_source_relations_from", table_name="source_relations")
