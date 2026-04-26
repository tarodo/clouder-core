"""users table

Revision ID: 20260426_11
Revises: 20260421_10
Create Date: 2026-04-26 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_11"
down_revision = "20260421_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("spotify_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_users_spotify_id",
        "users",
        ["spotify_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_users_spotify_id", table_name="users")
    op.drop_table("users")
