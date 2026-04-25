"""user_vendor_tokens table

Revision ID: 20260426_13
Revises: 20260426_12
Create Date: 2026-04-26 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_13"
down_revision = "20260426_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_vendor_tokens",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("access_token_enc", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("data_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "vendor", name="pk_user_vendor_tokens"),
    )


def downgrade() -> None:
    op.drop_table("user_vendor_tokens")
