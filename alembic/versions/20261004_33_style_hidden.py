"""hide styles from the catalog and the admin coverage matrix

Revision ID: 20261004_33
Revises: 20260920_32
Create Date: 2026-10-04 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261004_33"
down_revision = "20260920_32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_styles",
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("clouder_styles", "is_hidden")
