"""categories and category_tracks tables

Revision ID: 20260427_14
Revises: 20260426_13
Create Date: 2026-04-27 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260427_14"
down_revision = "20260426_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("style_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_categories_user"),
        sa.ForeignKeyConstraint(
            ["style_id"], ["clouder_styles.id"], name="fk_categories_style"
        ),
    )
    op.create_index(
        "uq_categories_user_style_normname",
        "categories",
        ["user_id", "style_id", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_categories_user_style_position",
        "categories",
        ["user_id", "style_id", "position"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_categories_user_created",
        "categories",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "category_tracks",
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_triage_block_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("category_id", "track_id"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name="fk_category_tracks_category"
        ),
        sa.ForeignKeyConstraint(
            ["track_id"], ["clouder_tracks.id"], name="fk_category_tracks_track"
        ),
        # NOTE: source_triage_block_id has no FK in spec-C; spec-D adds it.
    )
    op.create_index(
        "idx_category_tracks_category_added",
        "category_tracks",
        ["category_id", sa.text("added_at DESC"), "track_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_category_tracks_category_added", table_name="category_tracks"
    )
    op.drop_table("category_tracks")
    op.drop_index("idx_categories_user_created", table_name="categories")
    op.drop_index(
        "idx_categories_user_style_position", table_name="categories"
    )
    op.drop_index(
        "uq_categories_user_style_normname", table_name="categories"
    )
    op.drop_table("categories")
