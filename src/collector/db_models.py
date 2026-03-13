"""SQLAlchemy models used as schema source of truth for Alembic."""

from __future__ import annotations

from datetime import date as date_type, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    style_id: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class SourceEntity(Base):
    __tablename__ = "source_entities"
    __table_args__ = (
        PrimaryKeyConstraint("source", "entity_type", "external_id"),
        Index("idx_source_entities_run", "last_run_id"),
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    normalized_name: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingest_runs.run_id"), nullable=False
    )


class SourceRelation(Base):
    __tablename__ = "source_relations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "source",
            "from_entity_type",
            "from_external_id",
            "relation_type",
            "to_entity_type",
            "to_external_id",
        ),
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    from_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    to_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    to_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingest_runs.run_id"), nullable=False
    )


class ClouderArtist(Base):
    __tablename__ = "clouder_artists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ClouderLabel(Base):
    __tablename__ = "clouder_labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ClouderAlbum(Base):
    __tablename__ = "clouder_albums"
    __table_args__ = (
        Index("idx_album_match", "normalized_title", "release_date", "label_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(Text, nullable=False)
    release_date: Mapped[date_type | None] = mapped_column(Date)
    label_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clouder_labels.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ClouderTrack(Base):
    __tablename__ = "clouder_tracks"
    __table_args__ = (
        Index("idx_tracks_isrc", "isrc", postgresql_where=text("isrc IS NOT NULL")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(Text, nullable=False)
    mix_name: Mapped[str | None] = mapped_column(Text)
    isrc: Mapped[str | None] = mapped_column(String(64))
    bpm: Mapped[int | None] = mapped_column(Integer)
    length_ms: Mapped[int | None] = mapped_column(Integer)
    publish_date: Mapped[date_type | None] = mapped_column(Date)
    album_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clouder_albums.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ClouderTrackArtist(Base):
    __tablename__ = "clouder_track_artists"
    __table_args__ = (PrimaryKeyConstraint("track_id", "artist_id", "role"),)

    track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clouder_tracks.id"), nullable=False
    )
    artist_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clouder_artists.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'main'")
    )


class AISearchResult(Base):
    __tablename__ = "ai_search_results"
    __table_args__ = (
        Index(
            "uq_search_result",
            "entity_type",
            "entity_id",
            "prompt_slug",
            "prompt_version",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    prompt_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class IdentityMap(Base):
    __tablename__ = "identity_map"
    __table_args__ = (
        PrimaryKeyConstraint("source", "entity_type", "external_id"),
        Index("idx_identity_map_clouder", "clouder_entity_type", "clouder_id"),
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    clouder_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    clouder_id: Mapped[str] = mapped_column(String(36), nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
