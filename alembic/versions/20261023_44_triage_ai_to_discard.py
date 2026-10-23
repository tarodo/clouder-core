"""triage_blocks.ai_to_discard: the AI rule as a block option, on by default

A user can untick "AI tracks to DISCARD" when creating a block, like the disliked
labels / artists options. Existing blocks keep the rule (TRUE), as migration 43 applied it.

Revision ID: 20261023_44
Revises: 20261023_43
Create Date: 2026-10-23 08:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_44"
down_revision = "20261023_43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "triage_blocks",
        sa.Column("ai_to_discard", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
    )


def downgrade() -> None:
    op.drop_column("triage_blocks", "ai_to_discard")
