"""playlists.status column (active|completed)

Revision ID: 20260512_20
Revises: 20260512_19
Create Date: 2026-05-12 17:30:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260512_20"
down_revision = "20260512_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playlists",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.create_check_constraint(
        "ck_playlists_status",
        "playlists",
        "status IN ('active','completed')",
    )
    # Partial index helps the common "submenu / list with hide completed"
    # query: SELECT ... WHERE user_id = :u AND deleted_at IS NULL AND
    # status = 'active'. Categories submenu and frontend list page both
    # hit this path.
    op.create_index(
        "idx_playlists_user_active",
        "playlists",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL AND status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("idx_playlists_user_active", table_name="playlists")
    op.drop_constraint("ck_playlists_status", "playlists", type_="check")
    op.drop_column("playlists", "status")
