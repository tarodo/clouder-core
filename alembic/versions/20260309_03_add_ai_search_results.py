"""add ai_search_results table

Revision ID: 20260309_03
Revises: 20260308_02
Create Date: 2026-03-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260309_03"
down_revision = "20260308_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_search_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("prompt_slug", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.Column(
            "searched_at", sa.DateTime(timezone=True), nullable=False
        ),
    )
    op.create_index(
        "uq_search_result",
        "ai_search_results",
        ["entity_type", "entity_id", "prompt_slug", "prompt_version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_search_result", table_name="ai_search_results")
    op.drop_table("ai_search_results")
