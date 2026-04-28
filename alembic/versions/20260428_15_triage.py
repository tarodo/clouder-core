"""triage tables, spotify_release_date column, deferred FK from spec-C

Revision ID: 20260428_15
Revises: 20260427_14
Create Date: 2026-04-28 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_15"
down_revision = "20260427_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. triage_blocks
    op.create_table(
        "triage_blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("style_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'IN_PROGRESS'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_triage_blocks_user"
        ),
        sa.ForeignKeyConstraint(
            ["style_id"],
            ["clouder_styles.id"],
            name="fk_triage_blocks_style",
        ),
        sa.CheckConstraint(
            "date_to >= date_from", name="ck_triage_blocks_date_range"
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS','FINALIZED')",
            name="ck_triage_blocks_status",
        ),
    )
    op.create_index(
        "idx_triage_blocks_user_style_status",
        "triage_blocks",
        ["user_id", "style_id", "status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_triage_blocks_user_created",
        "triage_blocks",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 2. triage_buckets
    op.create_table(
        "triage_buckets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("triage_block_id", sa.String(length=36), nullable=False),
        sa.Column("bucket_type", sa.String(length=16), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column(
            "inactive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["triage_block_id"],
            ["triage_blocks.id"],
            name="fk_triage_buckets_block",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_triage_buckets_category",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING')",
            name="ck_triage_buckets_type",
        ),
        sa.CheckConstraint(
            "(bucket_type = 'STAGING') = (category_id IS NOT NULL)",
            name="ck_triage_buckets_staging_category",
        ),
    )
    op.create_index(
        "idx_triage_buckets_block",
        "triage_buckets",
        ["triage_block_id"],
    )
    op.create_index(
        "idx_triage_buckets_category",
        "triage_buckets",
        ["category_id"],
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )
    op.create_index(
        "uq_triage_buckets_block_category",
        "triage_buckets",
        ["triage_block_id", "category_id"],
        unique=True,
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )
    op.create_index(
        "uq_triage_buckets_block_type_tech",
        "triage_buckets",
        ["triage_block_id", "bucket_type"],
        unique=True,
        postgresql_where=sa.text("bucket_type <> 'STAGING'"),
    )

    # 3. triage_bucket_tracks
    op.create_table(
        "triage_bucket_tracks",
        sa.Column("triage_bucket_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("triage_bucket_id", "track_id"),
        sa.ForeignKeyConstraint(
            ["triage_bucket_id"],
            ["triage_buckets.id"],
            name="fk_triage_bucket_tracks_bucket",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["clouder_tracks.id"],
            name="fk_triage_bucket_tracks_track",
        ),
    )
    op.create_index(
        "idx_triage_bucket_tracks_bucket_added",
        "triage_bucket_tracks",
        ["triage_bucket_id", sa.text("added_at DESC"), "track_id"],
    )

    # 4. clouder_tracks.spotify_release_date
    op.add_column(
        "clouder_tracks",
        sa.Column("spotify_release_date", sa.Date(), nullable=True),
    )
    op.create_index(
        "idx_tracks_spotify_release_date",
        "clouder_tracks",
        ["spotify_release_date"],
        postgresql_where=sa.text("spotify_release_date IS NOT NULL"),
    )

    # 5. category_tracks.source_triage_block_id FK (deferred from spec-C D16)
    op.create_foreign_key(
        "fk_category_tracks_source_triage_block",
        "category_tracks",
        "triage_blocks",
        ["source_triage_block_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 6. GRANTs to clouder_app role (same pattern as spec-C migration)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON triage_blocks TO clouder_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON triage_buckets TO clouder_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON triage_bucket_tracks TO clouder_app"
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_category_tracks_source_triage_block",
        "category_tracks",
        type_="foreignkey",
    )
    op.drop_index(
        "idx_tracks_spotify_release_date", table_name="clouder_tracks"
    )
    op.drop_column("clouder_tracks", "spotify_release_date")

    op.drop_index(
        "idx_triage_bucket_tracks_bucket_added",
        table_name="triage_bucket_tracks",
    )
    op.drop_table("triage_bucket_tracks")

    op.drop_index(
        "uq_triage_buckets_block_type_tech", table_name="triage_buckets"
    )
    op.drop_index(
        "uq_triage_buckets_block_category", table_name="triage_buckets"
    )
    op.drop_index("idx_triage_buckets_category", table_name="triage_buckets")
    op.drop_index("idx_triage_buckets_block", table_name="triage_buckets")
    op.drop_table("triage_buckets")

    op.drop_index(
        "idx_triage_blocks_user_created", table_name="triage_blocks"
    )
    op.drop_index(
        "idx_triage_blocks_user_style_status", table_name="triage_blocks"
    )
    op.drop_table("triage_blocks")
