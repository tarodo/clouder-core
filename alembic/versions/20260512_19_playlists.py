"""playlists, playlist_tracks, user_imported_tracks + clouder_tracks.origin

Revision ID: 20260512_19
Revises: 20260511_18
Create Date: 2026-05-12 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260512_19"
down_revision = "20260511_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. clouder_tracks.origin
    op.add_column(
        "clouder_tracks",
        sa.Column(
            "origin",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'beatport'"),
        ),
    )
    op.create_check_constraint(
        "ck_clouder_tracks_origin",
        "clouder_tracks",
        "origin IN ('beatport','spotify_user_import')",
    )

    # 2. spotify_id partial UNIQUE (replaces the non-unique partial index)
    op.drop_index("idx_tracks_spotify_id", table_name="clouder_tracks")
    op.create_index(
        "uq_tracks_spotify_id",
        "clouder_tracks",
        ["spotify_id"],
        unique=True,
        postgresql_where=sa.text("spotify_id IS NOT NULL"),
    )

    # 3. playlists
    op.create_table(
        "playlists",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("cover_s3_key", sa.Text(), nullable=True),
        sa.Column("cover_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spotify_playlist_id", sa.Text(), nullable=True),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("needs_republish", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_playlists_user"),
    )
    op.create_index(
        "idx_playlists_user_created",
        "playlists",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_playlists_user_normname",
        "playlists",
        ["user_id", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_playlists_spotify_playlist_id",
        "playlists",
        ["spotify_playlist_id"],
        postgresql_where=sa.text("spotify_playlist_id IS NOT NULL"),
    )

    # 4. playlist_tracks
    op.create_table(
        "playlist_tracks",
        sa.Column("playlist_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("playlist_id", "track_id"),
        sa.ForeignKeyConstraint(
            ["playlist_id"], ["playlists.id"],
            name="fk_playlist_tracks_playlist", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"], ["clouder_tracks.id"],
            name="fk_playlist_tracks_track", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_playlist_tracks_position"),
    )
    # DEFERRABLE unique requires a CONSTRAINT (not a bare INDEX). Postgres does
    # not allow DEFERRABLE on CREATE UNIQUE INDEX; only CONSTRAINTs are deferrable.
    op.execute(
        "ALTER TABLE playlist_tracks "
        "ADD CONSTRAINT uq_playlist_tracks_playlist_position "
        "UNIQUE (playlist_id, position) DEFERRABLE INITIALLY DEFERRED"
    )
    op.create_index(
        "idx_playlist_tracks_playlist_position",
        "playlist_tracks",
        ["playlist_id", "position"],
    )

    # 5. user_imported_tracks
    op.create_table(
        "user_imported_tracks",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "track_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_user_imported_tracks_user", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"], ["clouder_tracks.id"],
            name="fk_user_imported_tracks_track", ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_user_imported_tracks_user",
        "user_imported_tracks",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_imported_tracks_user", table_name="user_imported_tracks")
    op.drop_table("user_imported_tracks")

    op.drop_index("idx_playlist_tracks_playlist_position", table_name="playlist_tracks")
    op.execute(
        "ALTER TABLE playlist_tracks "
        "DROP CONSTRAINT IF EXISTS uq_playlist_tracks_playlist_position"
    )
    op.drop_table("playlist_tracks")

    op.drop_index("idx_playlists_spotify_playlist_id", table_name="playlists")
    op.drop_index("uq_playlists_user_normname", table_name="playlists")
    op.drop_index("idx_playlists_user_created", table_name="playlists")
    op.drop_table("playlists")

    op.drop_index("uq_tracks_spotify_id", table_name="clouder_tracks")
    op.create_index(
        "idx_tracks_spotify_id",
        "clouder_tracks",
        ["spotify_id"],
        postgresql_where=sa.text("spotify_id IS NOT NULL"),
    )

    op.drop_constraint("ck_clouder_tracks_origin", "clouder_tracks", type_="check")
    op.drop_column("clouder_tracks", "origin")
