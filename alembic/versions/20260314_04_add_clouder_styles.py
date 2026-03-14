"""add clouder_styles table and style_id FK on clouder_tracks

Revision ID: 20260314_04
Revises: 20260309_03
Create Date: 2026-03-14 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260314_04"
down_revision = "20260309_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_styles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "clouder_tracks",
        sa.Column(
            "style_id",
            sa.String(36),
            sa.ForeignKey("clouder_styles.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("clouder_tracks", "style_id")
    op.drop_table("clouder_styles")
