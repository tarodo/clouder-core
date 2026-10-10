"""vendor rate limits: when a vendor banned us, until when to leave it alone

Revision ID: 20261010_35
Revises: 20261007_34
Create Date: 2026-10-10 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261010_35"
down_revision = "20261007_34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_rate_limits",
        sa.Column("vendor", sa.String(32), primary_key=True),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("vendor_rate_limits")
