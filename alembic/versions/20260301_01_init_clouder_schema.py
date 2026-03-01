"""init clouder schema

Revision ID: 20260301_01
Revises:
Create Date: 2026-03-01 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260301_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingest_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("style_id", sa.Integer(), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("raw_s3_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "source_entities",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("normalized_name", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["last_run_id"], ["ingest_runs.run_id"]),
        sa.PrimaryKeyConstraint("source", "entity_type", "external_id"),
    )
    op.create_index("idx_source_entities_run", "source_entities", ["last_run_id"])

    op.create_table(
        "source_relations",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("from_entity_type", sa.String(length=32), nullable=False),
        sa.Column("from_external_id", sa.String(length=64), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("to_entity_type", sa.String(length=32), nullable=False),
        sa.Column("to_external_id", sa.String(length=64), nullable=False),
        sa.Column("last_run_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["last_run_id"], ["ingest_runs.run_id"]),
        sa.PrimaryKeyConstraint(
            "source",
            "from_entity_type",
            "from_external_id",
            "relation_type",
            "to_entity_type",
            "to_external_id",
        ),
    )

    op.create_table(
        "clouder_artists",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "clouder_labels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "clouder_albums",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("label_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["label_id"], ["clouder_labels.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_album_match", "clouder_albums", ["normalized_title", "release_date", "label_id"])

    op.create_table(
        "clouder_tracks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("mix_name", sa.Text(), nullable=True),
        sa.Column("isrc", sa.String(length=64), nullable=True),
        sa.Column("bpm", sa.Integer(), nullable=True),
        sa.Column("length_ms", sa.Integer(), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("album_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["album_id"], ["clouder_albums.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tracks_isrc", "clouder_tracks", ["isrc"], unique=False, postgresql_where=sa.text("isrc IS NOT NULL"))

    op.create_table(
        "clouder_track_artists",
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("artist_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="main"),
        sa.ForeignKeyConstraint(["artist_id"], ["clouder_artists.id"]),
        sa.ForeignKeyConstraint(["track_id"], ["clouder_tracks.id"]),
        sa.PrimaryKeyConstraint("track_id", "artist_id", "role"),
    )

    op.create_table(
        "identity_map",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("clouder_entity_type", sa.String(length=32), nullable=False),
        sa.Column("clouder_id", sa.String(length=36), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source", "entity_type", "external_id"),
    )
    op.create_index("idx_identity_map_clouder", "identity_map", ["clouder_entity_type", "clouder_id"])


def downgrade() -> None:
    op.drop_index("idx_identity_map_clouder", table_name="identity_map")
    op.drop_table("identity_map")
    op.drop_table("clouder_track_artists")
    op.drop_index("idx_tracks_isrc", table_name="clouder_tracks")
    op.drop_table("clouder_tracks")
    op.drop_index("idx_album_match", table_name="clouder_albums")
    op.drop_table("clouder_albums")
    op.drop_table("clouder_labels")
    op.drop_table("clouder_artists")
    op.drop_table("source_relations")
    op.drop_index("idx_source_entities_run", table_name="source_entities")
    op.drop_table("source_entities")
    op.drop_table("ingest_runs")
