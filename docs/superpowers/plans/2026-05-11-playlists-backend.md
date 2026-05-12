# Playlists Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend playlists feature on top of CLOUDER: per-user playlists with name, description, cover (S3), Spotify track import, and one-tap publish/overwrite to Spotify.

**Architecture:** Single curation Lambda. Three new modules in `src/collector/curation/`: repository (Aurora Data API, user-scoped), service (validation + orchestration), Spotify user-OAuth client. One new migration. 12 new HTTP routes appended to existing `curation_handler.py` route table.

**Tech Stack:** Python 3.12 · Aurora Postgres via RDS Data API · SQLAlchemy / Alembic (migrations only) · Pydantic for request schemas · S3 (presigned PUT/GET for covers) · KMS envelope encryption for OAuth tokens (existing `collector.auth.kms_envelope`) · Spotify Web API · structlog · pytest.

**Spec:** `docs/superpowers/specs/2026-05-11-playlists-backend-design.md`

---

## File Structure

**New files:**

- `alembic/versions/20260512_19_playlists.py` — schema migration.
- `src/collector/curation/playlists_service.py` — pure helpers (validation, normalize, ref parser, reorder check).
- `src/collector/curation/playlists_repository.py` — Aurora Data API; every method takes `user_id`.
- `src/collector/curation/spotify_user_client.py` — user-OAuth Spotify Web API client + retry.
- `src/collector/curation/spotify_token_resolver.py` — read + KMS-decrypt + refresh `user_vendor_tokens.spotify`.
- `infra/curation_routes_playlists.tf` — append-only routes file.
- `tests/unit/test_playlists_service.py`
- `tests/unit/test_playlists_repository.py`
- `tests/unit/test_spotify_user_client.py`
- `tests/unit/test_spotify_token_resolver.py`
- `tests/integration/test_playlists_flow.py`

**Modified files:**

- `src/collector/curation/__init__.py` — new error classes.
- `src/collector/curation/schemas.py` — new Pydantic models for playlist requests.
- `src/collector/curation_handler.py` — +12 route handlers, append to `_ROUTE_TABLE`, new factory.
- `src/collector/storage.py` — `presigned_cover_put_url`, `presigned_cover_get_url`, `head_cover`, `read_cover_bytes`.
- `src/collector/db_models.py` — `Playlist`, `PlaylistTrack`, `UserImportedTrack` models + `ClouderTrack.origin` field (for alembic autogen parity).
- `scripts/generate_openapi.py` — append 12 ROUTES entries.
- `infra/curation.tf` — extend IAM (S3 `covers/*`, KMS decrypt for user-token key).

---

## Task 1: Migration 19 — schema changes

**Files:**

- Create: `alembic/versions/20260512_19_playlists.py`
- Modify: `src/collector/db_models.py` (append models, add `origin` to `ClouderTrack`)
- Test: smoke-test via `alembic upgrade head` against ephemeral pg

- [ ] **Step 1: Write the failing migration check**

Create `tests/unit/test_playlists_migration.py`:

```python
"""Sanity check that migration 19 has a clean revision chain."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_19_chain() -> None:
    m = _load_migration("20260512_19_playlists.py")
    assert m.revision == "20260512_19"
    assert m.down_revision == "20260511_18"


def test_migration_19_upgrade_downgrade_callable() -> None:
    m = _load_migration("20260512_19_playlists.py")
    assert callable(m.upgrade)
    assert callable(m.downgrade)
```

- [ ] **Step 2: Run test, verify it fails**

`pytest tests/unit/test_playlists_migration.py -q`
Expected: `FileNotFoundError` or import error.

- [ ] **Step 3: Create the migration**

Create `alembic/versions/20260512_19_playlists.py`:

```python
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
    # DEFERRABLE unique requires raw SQL — Alembic helper does not accept the modifier.
    op.execute(
        "CREATE UNIQUE INDEX uq_playlist_tracks_playlist_position "
        "ON playlist_tracks (playlist_id, position) "
        "DEFERRABLE INITIALLY DEFERRED"
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
    op.execute("DROP INDEX IF EXISTS uq_playlist_tracks_playlist_position")
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
```

- [ ] **Step 4: Append SQLAlchemy models in `db_models.py`**

Append at end of `src/collector/db_models.py` (mirrors `TrackTag` style):

```python
class Playlist(Base):
    __tablename__ = "playlists"
    __table_args__ = (
        Index(
            "idx_playlists_user_created",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_playlists_user_normname",
            "user_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_playlists_spotify_playlist_id",
            "spotify_playlist_id",
            postgresql_where=text("spotify_playlist_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    cover_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    spotify_playlist_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    needs_republish: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_playlist_tracks_position"),
        Index("idx_playlist_tracks_playlist_position", "playlist_id", "position"),
    )

    playlist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("playlists.id", ondelete="CASCADE"),
        primary_key=True,
    )
    track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clouder_tracks.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class UserImportedTrack(Base):
    __tablename__ = "user_imported_tracks"
    __table_args__ = (
        Index("idx_user_imported_tracks_user", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    track_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clouder_tracks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

Add `origin` column to existing `ClouderTrack` class (find the column block, append):

```python
    origin: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'beatport'")
    )
```

Verify `Integer` is imported in `db_models.py`; add to imports if missing.

- [ ] **Step 5: Run unit test, verify pass**

`pytest tests/unit/test_playlists_migration.py -q` → PASS.

- [ ] **Step 6: Run full migration against ephemeral pg**

```bash
docker run -d --rm -p 5433:5432 -e POSTGRES_PASSWORD=postgres --name pg-pltest postgres:16-alpine
sleep 3
PYTHONPATH=src ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/postgres' \
  .venv/bin/alembic upgrade head
PYTHONPATH=src ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/postgres' \
  .venv/bin/alembic downgrade -1
PYTHONPATH=src ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/postgres' \
  .venv/bin/alembic upgrade head
docker stop pg-pltest
```

Expected: no errors. If your local has port 5432 free, replace with that.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/20260512_19_playlists.py src/collector/db_models.py \
        tests/unit/test_playlists_migration.py
git commit -m "$(cat <<'EOF'
feat(playlists): add migration 19 + sqlalchemy models

Adds playlists, playlist_tracks, user_imported_tracks. Promotes
clouder_tracks.spotify_id partial index to UNIQUE so ON CONFLICT
import is idempotent. Adds clouder_tracks.origin discriminator.
EOF
)"
```

---

## Task 2: Curation error classes

**Files:**

- Modify: `src/collector/curation/__init__.py`
- Test: `tests/unit/test_playlists_errors.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_playlists_errors.py`:

```python
from __future__ import annotations

import pytest

from collector.curation import (
    ConfirmOverwriteRequiredError,
    CoverMissingError,
    CoverTooLargeError,
    InvalidSpotifyRefError,
    NothingToPublishError,
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
    PlaylistTrackLimitError,
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyRateLimitedError,
    SpotifyScopeInsufficientError,
    TrackNotInUserScopeError,
)


def test_each_error_carries_expected_code_and_status() -> None:
    cases = [
        (PlaylistNameConflictError("x"), "playlist_name_conflict", 409),
        (PlaylistLimitReachedError("x"), "playlist_limit_reached", 429),
        (PlaylistTrackLimitError("x"), "playlist_track_limit", 400),
        (TrackNotInUserScopeError("x", ["a"]), "track_not_in_user_scope", 404),
        (ConfirmOverwriteRequiredError("x"), "confirm_overwrite_required", 409),
        (SpotifyNotAuthorizedError("x"), "spotify_not_authorized", 412),
        (SpotifyScopeInsufficientError("x"), "spotify_scope_insufficient", 412),
        (SpotifyApiError("x"), "spotify_api_error", 502),
        (SpotifyRateLimitedError("x"), "spotify_rate_limited", 502),
        (InvalidSpotifyRefError("x"), "invalid_spotify_ref", 400),
        (CoverMissingError("x"), "cover_missing", 400),
        (CoverTooLargeError("x"), "cover_too_large", 400),
        (NothingToPublishError("x"), "nothing_to_publish", 400),
    ]
    for exc, code, status in cases:
        assert exc.error_code == code
        assert exc.http_status == status


def test_track_not_in_user_scope_carries_ids() -> None:
    exc = TrackNotInUserScopeError("missing", ["a", "b"])
    assert exc.missing_track_ids == ["a", "b"]


def test_playlist_not_found_uses_subclass_pattern() -> None:
    with pytest.raises(PlaylistNotFoundError):
        raise PlaylistNotFoundError()
```

- [ ] **Step 2: Run test, verify fail**

`pytest tests/unit/test_playlists_errors.py -q` → ImportError.

- [ ] **Step 3: Add errors to `src/collector/curation/__init__.py`**

Append after the existing tag-error block:

```python
# --- Playlists (spec 2026-05-11) -------------------------------------------


class PlaylistNotFoundError(NotFoundError):
    def __init__(self, message: str = "Playlist not found") -> None:
        super().__init__("playlist_not_found", message)


class PlaylistNameConflictError(NameConflictError):
    error_code = "playlist_name_conflict"


class PlaylistLimitReachedError(CurationError):
    error_code = "playlist_limit_reached"
    http_status = 429


class PlaylistTrackLimitError(CurationError):
    error_code = "playlist_track_limit"
    http_status = 400


class TrackNotInUserScopeError(CurationError):
    error_code = "track_not_in_user_scope"
    http_status = 404

    def __init__(self, message: str, missing_track_ids: list[str]) -> None:
        super().__init__(message)
        self.missing_track_ids = missing_track_ids


class ConfirmOverwriteRequiredError(CurationError):
    error_code = "confirm_overwrite_required"
    http_status = 409


class SpotifyNotAuthorizedError(CurationError):
    error_code = "spotify_not_authorized"
    http_status = 412


class SpotifyScopeInsufficientError(CurationError):
    error_code = "spotify_scope_insufficient"
    http_status = 412


class SpotifyApiError(CurationError):
    error_code = "spotify_api_error"
    http_status = 502


class SpotifyRateLimitedError(CurationError):
    error_code = "spotify_rate_limited"
    http_status = 502


class InvalidSpotifyRefError(CurationError):
    error_code = "invalid_spotify_ref"
    http_status = 400


class CoverMissingError(CurationError):
    error_code = "cover_missing"
    http_status = 400


class CoverTooLargeError(CurationError):
    error_code = "cover_too_large"
    http_status = 400


class NothingToPublishError(CurationError):
    error_code = "nothing_to_publish"
    http_status = 400
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_playlists_errors.py -q` → PASS.

- [ ] **Step 5: Extend handler error mapping**

In `src/collector/curation_handler.py`, find `_curation_error_response`. After the existing `TracksNotInSourceError` branch, add:

```python
    elif isinstance(exc, TrackNotInUserScopeError):
        payload["missing_track_ids"] = list(exc.missing_track_ids)
```

Also add `TrackNotInUserScopeError` to the imports at the top of the file (in the existing `from .curation import (...)` block).

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation/__init__.py src/collector/curation_handler.py \
        tests/unit/test_playlists_errors.py
git commit -m "$(cat <<'EOF'
feat(playlists): add curation error classes

Errors carry HTTP status + code consistent with categories/tags
pattern. TrackNotInUserScopeError surfaces missing_track_ids list
for client-side reconciliation.
EOF
)"
```

---

## Task 3: Service — name + ref-parser + reorder helpers

**Files:**

- Create: `src/collector/curation/playlists_service.py`
- Test: `tests/unit/test_playlists_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_playlists_service.py`:

```python
from __future__ import annotations

import pytest

from collector.curation import (
    InvalidSpotifyRefError,
    OrderMismatchError,
    ValidationError,
)
from collector.curation.playlists_service import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PLAYLISTS_PER_USER,
    MAX_TRACKS_PER_PLAYLIST,
    normalize_playlist_name,
    parse_spotify_ref,
    validate_description,
    validate_playlist_name,
    validate_reorder_set,
)


def test_normalize_lowercases_trims_collapses() -> None:
    assert normalize_playlist_name("  Tech  HOUSE  ") == "tech house"


def test_normalize_unicode_emoji() -> None:
    assert normalize_playlist_name("Hot 🔥 Beats") == "hot 🔥 beats"


def test_validate_name_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        validate_playlist_name("   ")


def test_validate_name_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        validate_playlist_name("x" * (MAX_NAME_LENGTH + 1))


def test_validate_name_rejects_control_chars() -> None:
    with pytest.raises(ValidationError):
        validate_playlist_name("bad\x07name")


def test_validate_description_allows_none() -> None:
    validate_description(None)


def test_validate_description_allows_empty_string() -> None:
    validate_description("")


def test_validate_description_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        validate_description("x" * (MAX_DESCRIPTION_LENGTH + 1))


def test_parse_uri_form() -> None:
    assert parse_spotify_ref("spotify:track:5xkAVrKKnHeBHb1Mqt6wEt") == "5xkAVrKKnHeBHb1Mqt6wEt"


def test_parse_url_form() -> None:
    assert (
        parse_spotify_ref("https://open.spotify.com/track/5xkAVrKKnHeBHb1Mqt6wEt")
        == "5xkAVrKKnHeBHb1Mqt6wEt"
    )


def test_parse_url_with_query_string() -> None:
    assert (
        parse_spotify_ref("https://open.spotify.com/track/5xkAVrKKnHeBHb1Mqt6wEt?si=abc")
        == "5xkAVrKKnHeBHb1Mqt6wEt"
    )


def test_parse_bare_id() -> None:
    assert parse_spotify_ref("5xkAVrKKnHeBHb1Mqt6wEt") == "5xkAVrKKnHeBHb1Mqt6wEt"


def test_parse_trims_whitespace() -> None:
    assert parse_spotify_ref("  5xkAVrKKnHeBHb1Mqt6wEt  ") == "5xkAVrKKnHeBHb1Mqt6wEt"


def test_parse_rejects_wrong_length() -> None:
    with pytest.raises(InvalidSpotifyRefError):
        parse_spotify_ref("short")


def test_parse_rejects_non_track_uri() -> None:
    with pytest.raises(InvalidSpotifyRefError):
        parse_spotify_ref("spotify:album:5xkAVrKKnHeBHb1Mqt6wEt")


def test_parse_rejects_malformed_chars() -> None:
    with pytest.raises(InvalidSpotifyRefError):
        parse_spotify_ref("!!!!!!!!!!!!!!!!!!!!!!")  # 22 chars but invalid base62


def test_reorder_detects_duplicate() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual=["a", "b", "c"], requested=["a", "a", "b"])


def test_reorder_detects_missing() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual=["a", "b", "c"], requested=["a", "b"])


def test_reorder_detects_extra() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual=["a", "b"], requested=["a", "b", "c"])


def test_reorder_accepts_permutation() -> None:
    validate_reorder_set(actual=["a", "b", "c"], requested=["c", "a", "b"])


def test_limits_exposed_as_module_constants() -> None:
    assert MAX_PLAYLISTS_PER_USER == 200
    assert MAX_TRACKS_PER_PLAYLIST == 1000
    assert MAX_NAME_LENGTH == 100
    assert MAX_DESCRIPTION_LENGTH == 300
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_playlists_service.py -q` → ImportError.

- [ ] **Step 3: Implement service helpers**

Create `src/collector/curation/playlists_service.py`:

```python
"""Pure helpers for playlists (spec 2026-05-11): validation, normalization,
Spotify ref parsing, reorder integrity check.

No I/O. No dependencies beyond stdlib + curation domain errors. Mirrors
shape and conventions of `categories_service.py`.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from . import InvalidSpotifyRefError, OrderMismatchError, ValidationError


MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 300
MAX_PLAYLISTS_PER_USER = 200
MAX_TRACKS_PER_PLAYLIST = 1000
MAX_IMPORT_REFS_PER_REQUEST = 50
MAX_COVER_BYTES = 262_144  # 256 KB — Spotify cover API limit.


# Spotify track IDs are base62, 22 chars.
_BASE62_RE = re.compile(r"^[0-9A-Za-z]{22}$")

# Match the three accepted forms.
_URI_RE = re.compile(r"^spotify:track:([0-9A-Za-z]{22})$")
_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/track/([0-9A-Za-z]{22})(?:\?.*)?$"
)


def normalize_playlist_name(name: str) -> str:
    """Lowercase + trim + collapse internal whitespace."""
    return " ".join(name.strip().lower().split())


def validate_playlist_name(name: str) -> None:
    trimmed = name.strip()
    if not trimmed:
        raise ValidationError("Name must be non-empty")
    if len(trimmed) > MAX_NAME_LENGTH:
        raise ValidationError(f"Name must be at most {MAX_NAME_LENGTH} characters")
    for ch in trimmed:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValidationError("Name must not contain control characters")


def validate_description(description: str | None) -> None:
    if description is None or description == "":
        return
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            f"Description must be at most {MAX_DESCRIPTION_LENGTH} characters"
        )
    for ch in description:
        if ord(ch) < 0x20 and ch not in ("\n", "\t"):
            raise ValidationError("Description contains control characters")


def parse_spotify_ref(ref: str) -> str:
    """Return the 22-char Spotify track ID or raise InvalidSpotifyRefError.

    Accepts: spotify:track:<id> | https://open.spotify.com/track/<id>[?q...] | <id>
    """
    if not isinstance(ref, str):
        raise InvalidSpotifyRefError("Spotify ref must be a string")
    cleaned = ref.strip()
    if not cleaned:
        raise InvalidSpotifyRefError("Spotify ref must be non-empty")

    m = _URI_RE.match(cleaned)
    if m:
        return m.group(1)

    m = _URL_RE.match(cleaned)
    if m:
        return m.group(1)

    if _BASE62_RE.match(cleaned):
        return cleaned

    raise InvalidSpotifyRefError(f"Unrecognized Spotify ref: {cleaned!r}")


def validate_reorder_set(
    *, actual: Iterable[str], requested: Sequence[str]
) -> None:
    """Same contract as categories_service.validate_reorder_set."""
    actual_set = set(actual)
    requested_set = set(requested)
    if len(requested) != len(requested_set):
        raise OrderMismatchError("track_ids contains duplicates")
    if actual_set != requested_set:
        raise OrderMismatchError(
            "track_ids must equal the current set of playlist tracks"
        )
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_playlists_service.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_service.py tests/unit/test_playlists_service.py
git commit -m "$(cat <<'EOF'
feat(playlists): add service helpers

Normalize, validate name/description, parse Spotify ref (uri / url /
bare id), reorder integrity check. Module constants expose limits
for the repository and handler layers.
EOF
)"
```

---

## Task 4: Repository — playlist CRUD (no tracks yet)

**Files:**

- Create: `src/collector/curation/playlists_repository.py`
- Test: `tests/unit/test_playlists_repository.py`

This task creates the repository module with playlist-level CRUD only — track operations land in Task 5, cover in Task 6, publish state in Task 7, scope check + import in Task 8.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_playlists_repository.py`:

```python
"""Unit tests for PlaylistsRepository.

DataAPIClient is stubbed with a MagicMock that returns canned rows per
SQL fragment match — same pattern as test_categories_repository.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
)
from collector.curation.playlists_repository import (
    PlaylistRow,
    PlaylistsRepository,
)


def _utc() -> datetime:
    return datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def _make_repo(data_api: MagicMock) -> PlaylistsRepository:
    return PlaylistsRepository(data_api=data_api)


def _make_data_api(rows_by_sql_substring: dict[str, list[dict]]) -> MagicMock:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx-1"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql: str, params=None, transaction_id=None):
        for needle, rows in rows_by_sql_substring.items():
            if needle in sql:
                return rows
        return []

    api.execute.side_effect = _execute
    return api


def test_create_inserts_row_and_returns_playlist() -> None:
    api = _make_data_api({
        "SELECT COUNT(*) AS cnt FROM playlists": [{"cnt": 5}],
        "INSERT INTO playlists": [{
            "id": "p-1",
            "user_id": "u-1",
            "name": "My Set",
            "normalized_name": "my set",
            "description": None,
            "is_public": False,
            "cover_s3_key": None,
            "cover_uploaded_at": None,
            "spotify_playlist_id": None,
            "last_published_at": None,
            "needs_republish": False,
            "track_count": 0,
            "created_at": _utc().isoformat(),
            "updated_at": _utc().isoformat(),
        }],
    })
    repo = _make_repo(api)
    row = repo.create(
        user_id="u-1", playlist_id="p-1", name="My Set",
        normalized_name="my set", description=None, is_public=False, now=_utc(),
    )
    assert isinstance(row, PlaylistRow)
    assert row.id == "p-1"
    assert row.track_count == 0


def test_create_raises_limit_reached_at_200() -> None:
    api = _make_data_api({
        "SELECT COUNT(*) AS cnt FROM playlists": [{"cnt": 200}],
    })
    repo = _make_repo(api)
    with pytest.raises(PlaylistLimitReachedError):
        repo.create(
            user_id="u-1", playlist_id="p-x", name="N",
            normalized_name="n", description=None, is_public=False, now=_utc(),
        )


def test_create_translates_unique_violation_to_name_conflict() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx-1"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT COUNT(*) AS cnt FROM playlists" in sql:
            return [{"cnt": 0}]
        if "INSERT INTO playlists" in sql:
            raise RuntimeError(
                "duplicate key value violates unique constraint "
                "\"uq_playlists_user_normname\""
            )
        return []

    api.execute.side_effect = _execute
    repo = _make_repo(api)
    with pytest.raises(PlaylistNameConflictError):
        repo.create(
            user_id="u-1", playlist_id="p-x", name="dup",
            normalized_name="dup", description=None, is_public=False, now=_utc(),
        )


def test_get_returns_none_for_unknown_id() -> None:
    api = _make_data_api({})
    repo = _make_repo(api)
    assert repo.get(user_id="u-1", playlist_id="missing") is None


def test_get_filters_soft_deleted() -> None:
    api = MagicMock()
    captured = {}

    def _execute(sql, params=None, transaction_id=None):
        captured["sql"] = sql
        captured["params"] = params
        return []

    api.execute.side_effect = _execute
    api.transaction.return_value.__enter__.return_value = "tx"
    repo = _make_repo(api)
    repo.get(user_id="u-1", playlist_id="p-1")
    assert "deleted_at IS NULL" in captured["sql"]
    assert captured["params"]["user_id"] == "u-1"


def test_soft_delete_returns_false_when_no_row_affected() -> None:
    api = _make_data_api({"UPDATE playlists SET deleted_at": []})
    repo = _make_repo(api)
    assert repo.soft_delete(user_id="u-1", playlist_id="p-1", now=_utc()) is False


def test_soft_delete_returns_true_when_row_affected() -> None:
    api = _make_data_api({
        "UPDATE playlists SET deleted_at": [{"id": "p-1"}],
    })
    repo = _make_repo(api)
    assert repo.soft_delete(user_id="u-1", playlist_id="p-1", now=_utc()) is True


def test_patch_raises_not_found_when_missing() -> None:
    api = _make_data_api({})
    repo = _make_repo(api)
    with pytest.raises(PlaylistNotFoundError):
        repo.patch(
            user_id="u-1", playlist_id="missing",
            name="new", normalized_name="new",
            description=None, is_public=None, now=_utc(),
        )
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_playlists_repository.py -q` → ImportError.

- [ ] **Step 3: Implement repository CRUD**

Create `src/collector/curation/playlists_repository.py`:

```python
"""Aurora Data API repository for playlists (spec 2026-05-11).

Tenancy: every method takes user_id and includes it in WHERE.
Cross-user access yields no rows → handler maps to 404.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from collector.data_api import DataAPIClient
from collector.logging_utils import log_event
from collector.settings import get_data_api_settings

from . import (
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
)
from .playlists_service import MAX_PLAYLISTS_PER_USER


@dataclass(frozen=True)
class PlaylistRow:
    id: str
    user_id: str
    name: str
    normalized_name: str
    description: str | None
    is_public: bool
    cover_s3_key: str | None
    cover_uploaded_at: str | None
    spotify_playlist_id: str | None
    last_published_at: str | None
    needs_republish: bool
    track_count: int
    created_at: str
    updated_at: str


_PLAYLIST_SELECT = """
    SELECT
        p.id, p.user_id, p.name, p.normalized_name, p.description,
        p.is_public, p.cover_s3_key, p.cover_uploaded_at,
        p.spotify_playlist_id, p.last_published_at, p.needs_republish,
        p.created_at, p.updated_at,
        COALESCE(t.cnt, 0) AS track_count
    FROM playlists p
    LEFT JOIN (
        SELECT playlist_id, COUNT(*) AS cnt
        FROM playlist_tracks
        GROUP BY playlist_id
    ) t ON t.playlist_id = p.id
"""


def _row(raw: Mapping[str, Any]) -> PlaylistRow:
    return PlaylistRow(
        id=raw["id"],
        user_id=raw["user_id"],
        name=raw["name"],
        normalized_name=raw["normalized_name"],
        description=raw.get("description"),
        is_public=bool(raw["is_public"]),
        cover_s3_key=raw.get("cover_s3_key"),
        cover_uploaded_at=(
            str(raw["cover_uploaded_at"])
            if raw.get("cover_uploaded_at") else None
        ),
        spotify_playlist_id=raw.get("spotify_playlist_id"),
        last_published_at=(
            str(raw["last_published_at"])
            if raw.get("last_published_at") else None
        ),
        needs_republish=bool(raw["needs_republish"]),
        track_count=int(raw.get("track_count") or 0),
        created_at=str(raw["created_at"]),
        updated_at=str(raw["updated_at"]),
    )


class PlaylistsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # ---------- CRUD ---------------------------------------------------------

    def create(
        self,
        *,
        user_id: str,
        playlist_id: str,
        name: str,
        normalized_name: str,
        description: str | None,
        is_public: bool,
        now: datetime,
    ) -> PlaylistRow:
        with self._data_api.transaction() as tx_id:
            count_rows = self._data_api.execute(
                "SELECT COUNT(*) AS cnt FROM playlists "
                "WHERE user_id = :user_id AND deleted_at IS NULL",
                {"user_id": user_id},
                transaction_id=tx_id,
            )
            cnt = int(count_rows[0]["cnt"]) if count_rows else 0
            if cnt >= MAX_PLAYLISTS_PER_USER:
                raise PlaylistLimitReachedError(
                    f"User has reached {MAX_PLAYLISTS_PER_USER} active playlists"
                )

            try:
                rows = self._data_api.execute(
                    """
                    INSERT INTO playlists (
                        id, user_id, name, normalized_name, description,
                        is_public, cover_s3_key, cover_uploaded_at,
                        spotify_playlist_id, last_published_at, needs_republish,
                        created_at, updated_at, deleted_at
                    ) VALUES (
                        :id, :user_id, :name, :normalized_name, :description,
                        :is_public, NULL, NULL,
                        NULL, NULL, FALSE,
                        :now, :now, NULL
                    )
                    RETURNING id, user_id, name, normalized_name, description,
                              is_public, cover_s3_key, cover_uploaded_at,
                              spotify_playlist_id, last_published_at,
                              needs_republish, 0 AS track_count,
                              created_at, updated_at
                    """,
                    {
                        "id": playlist_id,
                        "user_id": user_id,
                        "name": name,
                        "normalized_name": normalized_name,
                        "description": description,
                        "is_public": is_public,
                        "now": now,
                    },
                    transaction_id=tx_id,
                )
            except Exception as exc:
                if "uq_playlists_user_normname" in str(exc):
                    raise PlaylistNameConflictError(
                        "Playlist name already exists"
                    ) from exc
                raise
            return _row(rows[0])

    def get(self, *, user_id: str, playlist_id: str) -> PlaylistRow | None:
        rows = self._data_api.execute(
            _PLAYLIST_SELECT
            + " WHERE p.id = :id AND p.user_id = :user_id "
              "AND p.deleted_at IS NULL",
            {"id": playlist_id, "user_id": user_id},
        )
        return _row(rows[0]) if rows else None

    def list_all(
        self, *, user_id: str, limit: int, offset: int
    ) -> tuple[list[PlaylistRow], int]:
        rows = self._data_api.execute(
            _PLAYLIST_SELECT
            + " WHERE p.user_id = :user_id AND p.deleted_at IS NULL "
              "ORDER BY p.created_at DESC, p.id ASC "
              "LIMIT :limit OFFSET :offset",
            {"user_id": user_id, "limit": limit, "offset": offset},
        )
        total_rows = self._data_api.execute(
            "SELECT COUNT(*) AS total FROM playlists "
            "WHERE user_id = :user_id AND deleted_at IS NULL",
            {"user_id": user_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        return [_row(r) for r in rows], total

    def patch(
        self,
        *,
        user_id: str,
        playlist_id: str,
        name: str | None,
        normalized_name: str | None,
        description: str | None,
        is_public: bool | None,
        now: datetime,
    ) -> PlaylistRow:
        """Partial update. None values mean "leave as is".

        If the row is already published (spotify_playlist_id IS NOT NULL),
        marks needs_republish=TRUE inside the same statement.
        """
        # Build COALESCE-style SQL so unset fields are left unchanged.
        try:
            rows = self._data_api.execute(
                """
                UPDATE playlists SET
                    name = COALESCE(:name, name),
                    normalized_name = COALESCE(:normalized_name, normalized_name),
                    description = CASE WHEN :description_set THEN :description ELSE description END,
                    is_public = COALESCE(:is_public, is_public),
                    needs_republish = CASE
                        WHEN spotify_playlist_id IS NOT NULL THEN TRUE
                        ELSE needs_republish
                    END,
                    updated_at = :now
                WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
                RETURNING id, user_id, name, normalized_name, description,
                          is_public, cover_s3_key, cover_uploaded_at,
                          spotify_playlist_id, last_published_at, needs_republish,
                          created_at, updated_at
                """,
                {
                    "id": playlist_id,
                    "user_id": user_id,
                    "name": name,
                    "normalized_name": normalized_name,
                    "description": description,
                    "description_set": description is not None,
                    "is_public": is_public,
                    "now": now,
                },
            )
        except Exception as exc:
            if "uq_playlists_user_normname" in str(exc):
                raise PlaylistNameConflictError(
                    "Playlist name already exists"
                ) from exc
            raise
        if not rows:
            raise PlaylistNotFoundError()
        # track_count not returned by UPDATE; re-select to attach it.
        return self.get(user_id=user_id, playlist_id=playlist_id) or _row(
            {**rows[0], "track_count": 0}
        )

    def soft_delete(
        self, *, user_id: str, playlist_id: str, now: datetime
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE playlists SET deleted_at = :now, updated_at = :now
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {"id": playlist_id, "user_id": user_id, "now": now},
        )
        return bool(rows)


def create_default_playlists_repository() -> PlaylistsRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return PlaylistsRepository(data_api=data_api)
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_playlists_repository.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py \
        tests/unit/test_playlists_repository.py
git commit -m "$(cat <<'EOF'
feat(playlists): repository CRUD for playlists

create / get / list_all / patch / soft_delete with user_id
tenancy. PATCH marks needs_republish=true when spotify_playlist_id
is set. Unique violation surfaces as PlaylistNameConflictError.
EOF
)"
```

---

## Task 5: Repository — tracks (append / remove / reorder / list)

**Files:**

- Modify: `src/collector/curation/playlists_repository.py`
- Modify: `tests/unit/test_playlists_repository.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_playlists_repository.py`:

```python
from collector.curation import (
    OrderMismatchError,
    PlaylistTrackLimitError,
)
from collector.curation.playlists_repository import PlaylistTrackRow


def test_append_tracks_uses_max_position_plus_one() -> None:
    captured_inserts: list[dict] = []
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT COUNT(*) AS cnt FROM playlist_tracks" in sql:
            return [{"cnt": 3}]
        if "SELECT COALESCE(MAX(position), -1)" in sql:
            return [{"max_pos": 4}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return []  # no duplicates yet
        return []

    def _batch_execute(sql, parameter_sets, transaction_id=None):
        captured_inserts.extend(parameter_sets)

    api.execute.side_effect = _execute
    api.batch_execute.side_effect = _batch_execute

    repo = PlaylistsRepository(api)
    result = repo.append_tracks(
        user_id="u-1",
        playlist_id="p-1",
        track_ids=["t-a", "t-b"],
        now=_utc(),
    )
    assert result.added_track_ids == ["t-a", "t-b"]
    assert result.skipped_duplicates == []
    assert result.position_after == 7
    assert [p["position"] for p in captured_inserts] == [5, 6]


def test_append_tracks_dedups_against_existing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT COUNT(*) AS cnt FROM playlist_tracks" in sql:
            return [{"cnt": 1}]
        if "SELECT COALESCE(MAX(position), -1)" in sql:
            return [{"max_pos": 0}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return [{"track_id": "t-a"}]
        return []

    api.execute.side_effect = _execute
    api.batch_execute = MagicMock()

    repo = PlaylistsRepository(api)
    result = repo.append_tracks(
        user_id="u-1", playlist_id="p-1",
        track_ids=["t-a", "t-b"], now=_utc(),
    )
    assert result.added_track_ids == ["t-b"]
    assert result.skipped_duplicates == ["t-a"]


def test_append_tracks_rejects_when_over_limit() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT COUNT(*) AS cnt FROM playlist_tracks" in sql:
            return [{"cnt": 999}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return []
        if "SELECT COALESCE(MAX(position), -1)" in sql:
            return [{"max_pos": 998}]
        return []

    api.execute.side_effect = _execute
    api.batch_execute = MagicMock()
    repo = PlaylistsRepository(api)
    with pytest.raises(PlaylistTrackLimitError):
        repo.append_tracks(
            user_id="u-1", playlist_id="p-1",
            track_ids=["a", "b"], now=_utc(),
        )


def test_remove_track_redenses_positions() -> None:
    captured = []
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        captured.append((sql.strip().split()[0], params))
        if "SELECT position FROM playlist_tracks" in sql:
            return [{"position": 2}]
        if "DELETE FROM playlist_tracks" in sql:
            return [{"track_id": "t-1"}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    removed = repo.remove_track(user_id="u-1", playlist_id="p-1", track_id="t-1")
    assert removed is True
    assert any("UPDATE" in op for op, _ in captured)


def test_remove_track_returns_false_when_missing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT position FROM playlist_tracks" in sql:
            return []
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    assert repo.remove_track(user_id="u-1", playlist_id="p-1", track_id="x") is False


def test_reorder_rejects_mismatched_set() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    api.execute.side_effect = lambda *a, **k: [
        {"track_id": "t-1"}, {"track_id": "t-2"},
    ] if "SELECT track_id FROM playlist_tracks" in a[0] else []
    repo = PlaylistsRepository(api)
    with pytest.raises(OrderMismatchError):
        repo.reorder_tracks(
            user_id="u-1", playlist_id="p-1",
            ordered_track_ids=["t-1", "t-2", "t-3"], now=_utc(),
        )


def test_reorder_accepts_permutation_and_emits_updates() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT track_id FROM playlist_tracks" in sql:
            return [{"track_id": "t-1"}, {"track_id": "t-2"}]
        return []

    batched = []
    api.execute.side_effect = _execute
    api.batch_execute.side_effect = (
        lambda sql, parameter_sets, transaction_id=None: batched.extend(parameter_sets)
    )
    repo = PlaylistsRepository(api)
    repo.reorder_tracks(
        user_id="u-1", playlist_id="p-1",
        ordered_track_ids=["t-2", "t-1"], now=_utc(),
    )
    assert {(p["track_id"], p["position"]) for p in batched} == {
        ("t-2", 0), ("t-1", 1),
    }


def test_list_tracks_returns_rows_with_position() -> None:
    api = _make_data_api({
        "FROM playlist_tracks pt": [
            {
                "track_id": "t-1", "position": 0, "added_at": _utc().isoformat(),
                "title": "Title A", "spotify_id": "s-a", "isrc": None,
                "length_ms": 200000, "origin": "beatport",
            },
        ],
        "SELECT COUNT(*) AS total FROM playlist_tracks pt2": [{"total": 1}],
    })
    repo = PlaylistsRepository(api)
    rows, total = repo.list_tracks(
        user_id="u-1", playlist_id="p-1", limit=50, offset=0,
    )
    assert total == 1
    assert isinstance(rows[0], PlaylistTrackRow)
    assert rows[0].position == 0
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_playlists_repository.py -q` → fails on missing methods.

- [ ] **Step 3: Add methods + `PlaylistTrackRow` to repository**

Append to `playlists_repository.py`:

```python
from .playlists_service import MAX_TRACKS_PER_PLAYLIST, validate_reorder_set


@dataclass(frozen=True)
class PlaylistTrackRow:
    track_id: str
    position: int
    added_at: str
    title: str
    spotify_id: str | None
    isrc: str | None
    length_ms: int | None
    origin: str


@dataclass(frozen=True)
class AppendTracksResult:
    added_track_ids: list[str]
    skipped_duplicates: list[str]
    position_after: int


class PlaylistsRepository:
    # ... existing methods stay ...

    # ---------- Tracks -------------------------------------------------------

    def append_tracks(
        self,
        *,
        user_id: str,
        playlist_id: str,
        track_ids: list[str],
        now: datetime,
    ) -> AppendTracksResult:
        if not track_ids:
            return AppendTracksResult([], [], 0)
        with self._data_api.transaction() as tx_id:
            # Confirm playlist exists for user.
            owner_rows = self._data_api.execute(
                "SELECT 1 AS ok FROM playlists "
                "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
                {"id": playlist_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not owner_rows:
                raise PlaylistNotFoundError()

            count_rows = self._data_api.execute(
                "SELECT COUNT(*) AS cnt FROM playlist_tracks "
                "WHERE playlist_id = :id",
                {"id": playlist_id},
                transaction_id=tx_id,
            )
            current = int(count_rows[0]["cnt"]) if count_rows else 0

            existing_rows = self._data_api.execute(
                "SELECT track_id FROM playlist_tracks "
                "WHERE playlist_id = :id AND track_id = ANY(:ids)",
                {"id": playlist_id, "ids": track_ids},
                transaction_id=tx_id,
            )
            existing = {r["track_id"] for r in existing_rows}

            to_add = [t for t in track_ids if t not in existing]
            skipped = [t for t in track_ids if t in existing]

            if current + len(to_add) > MAX_TRACKS_PER_PLAYLIST:
                raise PlaylistTrackLimitError(
                    f"Cannot exceed {MAX_TRACKS_PER_PLAYLIST} tracks per playlist"
                )

            max_rows = self._data_api.execute(
                "SELECT COALESCE(MAX(position), -1) AS max_pos "
                "FROM playlist_tracks WHERE playlist_id = :id",
                {"id": playlist_id},
                transaction_id=tx_id,
            )
            start = int(max_rows[0]["max_pos"]) + 1

            if to_add:
                self._data_api.batch_execute(
                    "INSERT INTO playlist_tracks "
                    "(playlist_id, track_id, position, added_at) "
                    "VALUES (:playlist_id, :track_id, :position, :now)",
                    [
                        {
                            "playlist_id": playlist_id,
                            "track_id": t,
                            "position": start + i,
                            "now": now,
                        }
                        for i, t in enumerate(to_add)
                    ],
                    transaction_id=tx_id,
                )
                self._mark_dirty_if_published(playlist_id, now, tx_id)

            return AppendTracksResult(
                added_track_ids=to_add,
                skipped_duplicates=skipped,
                position_after=start + len(to_add),
            )

    def remove_track(
        self,
        *,
        user_id: str,
        playlist_id: str,
        track_id: str,
    ) -> bool:
        with self._data_api.transaction() as tx_id:
            owner_rows = self._data_api.execute(
                "SELECT 1 AS ok FROM playlists "
                "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
                {"id": playlist_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not owner_rows:
                raise PlaylistNotFoundError()

            pos_rows = self._data_api.execute(
                "SELECT position FROM playlist_tracks "
                "WHERE playlist_id = :id AND track_id = :tid",
                {"id": playlist_id, "tid": track_id},
                transaction_id=tx_id,
            )
            if not pos_rows:
                return False
            removed_pos = int(pos_rows[0]["position"])

            self._data_api.execute(
                "DELETE FROM playlist_tracks "
                "WHERE playlist_id = :id AND track_id = :tid",
                {"id": playlist_id, "tid": track_id},
                transaction_id=tx_id,
            )
            self._data_api.execute(
                "UPDATE playlist_tracks SET position = position - 1 "
                "WHERE playlist_id = :id AND position > :pos",
                {"id": playlist_id, "pos": removed_pos},
                transaction_id=tx_id,
            )
            now = datetime.now()  # naive — only used inside the txn for updated_at
            self._mark_dirty_if_published(playlist_id, now, tx_id)
            return True

    def reorder_tracks(
        self,
        *,
        user_id: str,
        playlist_id: str,
        ordered_track_ids: list[str],
        now: datetime,
    ) -> None:
        with self._data_api.transaction() as tx_id:
            owner_rows = self._data_api.execute(
                "SELECT 1 AS ok FROM playlists "
                "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
                {"id": playlist_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not owner_rows:
                raise PlaylistNotFoundError()

            current = self._data_api.execute(
                "SELECT track_id FROM playlist_tracks WHERE playlist_id = :id",
                {"id": playlist_id},
                transaction_id=tx_id,
            )
            actual_ids = [r["track_id"] for r in current]
            validate_reorder_set(actual=actual_ids, requested=ordered_track_ids)

            # Two-phase: shift everyone out, then put them back with desired
            # positions. Avoids stepping on the (playlist_id, position) unique
            # even though it is DEFERRABLE — keeps the SQL simple.
            self._data_api.execute(
                "UPDATE playlist_tracks "
                "SET position = position + :offset "
                "WHERE playlist_id = :id",
                {"id": playlist_id, "offset": len(actual_ids) + 1},
                transaction_id=tx_id,
            )
            self._data_api.batch_execute(
                "UPDATE playlist_tracks SET position = :position "
                "WHERE playlist_id = :playlist_id AND track_id = :track_id",
                [
                    {"playlist_id": playlist_id, "track_id": t, "position": i}
                    for i, t in enumerate(ordered_track_ids)
                ],
                transaction_id=tx_id,
            )
            self._mark_dirty_if_published(playlist_id, now, tx_id)

    def list_tracks(
        self,
        *,
        user_id: str,
        playlist_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[PlaylistTrackRow], int]:
        # Ownership check first.
        owner = self._data_api.execute(
            "SELECT 1 AS ok FROM playlists "
            "WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL",
            {"id": playlist_id, "user_id": user_id},
        )
        if not owner:
            raise PlaylistNotFoundError()
        rows = self._data_api.execute(
            """
            SELECT pt.track_id, pt.position, pt.added_at,
                   t.title, t.spotify_id, t.isrc, t.length_ms, t.origin
            FROM playlist_tracks pt
            JOIN clouder_tracks t ON t.id = pt.track_id
            WHERE pt.playlist_id = :id
            ORDER BY pt.position ASC
            LIMIT :limit OFFSET :offset
            """,
            {"id": playlist_id, "limit": limit, "offset": offset},
        )
        total_rows = self._data_api.execute(
            "SELECT COUNT(*) AS total FROM playlist_tracks pt2 "
            "WHERE pt2.playlist_id = :id",
            {"id": playlist_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        out = [
            PlaylistTrackRow(
                track_id=r["track_id"],
                position=int(r["position"]),
                added_at=str(r["added_at"]),
                title=r["title"],
                spotify_id=r.get("spotify_id"),
                isrc=r.get("isrc"),
                length_ms=(int(r["length_ms"]) if r.get("length_ms") else None),
                origin=r.get("origin") or "beatport",
            )
            for r in rows
        ]
        return out, total

    # ---------- Helpers ------------------------------------------------------

    def _mark_dirty_if_published(
        self, playlist_id: str, now: datetime, tx_id: str
    ) -> None:
        self._data_api.execute(
            "UPDATE playlists SET needs_republish = TRUE, updated_at = :now "
            "WHERE id = :id AND spotify_playlist_id IS NOT NULL",
            {"id": playlist_id, "now": now},
            transaction_id=tx_id,
        )
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_playlists_repository.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py \
        tests/unit/test_playlists_repository.py
git commit -m "$(cat <<'EOF'
feat(playlists): track append / remove / reorder / list

Append dedupes against existing rows and uses max(position)+1.
Remove re-denses positions in-transaction. Reorder validates the
exact track set and shifts everyone before reapplying desired
positions. All mutations mark needs_republish when published.
EOF
)"
```

---

## Task 6: Repository — cover + publish-state methods

**Files:**

- Modify: `src/collector/curation/playlists_repository.py`
- Modify: `tests/unit/test_playlists_repository.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_playlists_repository.py`:

```python
def test_set_cover_updates_row_and_marks_dirty() -> None:
    captured = {}
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        captured.setdefault("calls", []).append((sql, params))
        if "RETURNING" in sql:
            return [{"id": "p-1"}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    ok = repo.set_cover(
        user_id="u-1", playlist_id="p-1",
        s3_key="covers/u-1/p-1/123.jpg", now=_utc(),
    )
    assert ok is True
    sqls = " | ".join(s for s, _ in captured["calls"])
    assert "cover_s3_key" in sqls
    assert "needs_republish" in sqls


def test_set_cover_returns_false_when_playlist_missing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    api.execute.side_effect = lambda *a, **k: []
    repo = PlaylistsRepository(api)
    assert repo.set_cover(
        user_id="u-1", playlist_id="p-1",
        s3_key="x", now=_utc(),
    ) is False


def test_clear_cover_returns_true_when_affected() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    api.execute.side_effect = lambda *a, **k: [{"id": "p-1"}]
    repo = PlaylistsRepository(api)
    assert repo.clear_cover(user_id="u-1", playlist_id="p-1", now=_utc()) is True


def test_set_publish_state_persists_and_clears_dirty() -> None:
    api = MagicMock()
    captured = {}

    def _execute(sql, params=None, transaction_id=None):
        captured["sql"] = sql
        captured["params"] = params
        return [{"id": "p-1"}]

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    repo.set_publish_state(
        user_id="u-1", playlist_id="p-1",
        spotify_playlist_id="spt-abc", now=_utc(),
    )
    assert "needs_republish = FALSE" in captured["sql"]
    assert captured["params"]["spotify_playlist_id"] == "spt-abc"
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_playlists_repository.py -q` → fails on missing methods.

- [ ] **Step 3: Add methods to repository**

Append to `playlists_repository.py`:

```python
    # ---------- Cover --------------------------------------------------------

    def set_cover(
        self,
        *,
        user_id: str,
        playlist_id: str,
        s3_key: str,
        now: datetime,
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE playlists SET
                cover_s3_key = :s3_key,
                cover_uploaded_at = :now,
                updated_at = :now,
                needs_republish = CASE
                    WHEN spotify_playlist_id IS NOT NULL THEN TRUE
                    ELSE needs_republish
                END
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {"id": playlist_id, "user_id": user_id, "s3_key": s3_key, "now": now},
        )
        return bool(rows)

    def clear_cover(
        self,
        *,
        user_id: str,
        playlist_id: str,
        now: datetime,
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE playlists SET
                cover_s3_key = NULL,
                cover_uploaded_at = NULL,
                updated_at = :now,
                needs_republish = CASE
                    WHEN spotify_playlist_id IS NOT NULL THEN TRUE
                    ELSE needs_republish
                END
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {"id": playlist_id, "user_id": user_id, "now": now},
        )
        return bool(rows)

    # ---------- Publish state -----------------------------------------------

    def set_publish_state(
        self,
        *,
        user_id: str,
        playlist_id: str,
        spotify_playlist_id: str,
        now: datetime,
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE playlists SET
                spotify_playlist_id = :spotify_playlist_id,
                last_published_at = :now,
                needs_republish = FALSE,
                updated_at = :now
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "id": playlist_id,
                "user_id": user_id,
                "spotify_playlist_id": spotify_playlist_id,
                "now": now,
            },
        )
        return bool(rows)
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_playlists_repository.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py \
        tests/unit/test_playlists_repository.py
git commit -m "$(cat <<'EOF'
feat(playlists): repository cover + publish-state methods

set_cover / clear_cover stamp updated_at and flip needs_republish
when the playlist is already published. set_publish_state writes
spotify_playlist_id, last_published_at, clears needs_republish.
EOF
)"
```

---

## Task 7: Repository — scope check, import upsert, user-imported marker

**Files:**

- Modify: `src/collector/curation/playlists_repository.py`
- Modify: `tests/unit/test_playlists_repository.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_validate_tracks_in_scope_returns_subset() -> None:
    api = _make_data_api({
        "SELECT t.id": [{"id": "t-1"}, {"id": "t-3"}],
    })
    repo = PlaylistsRepository(api)
    visible = repo.validate_tracks_in_scope(
        user_id="u-1", track_ids=["t-1", "t-2", "t-3"],
    )
    assert visible == {"t-1", "t-3"}


def test_upsert_imported_track_uses_existing_when_spotify_id_matches() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT id FROM clouder_tracks WHERE spotify_id" in sql:
            return [{"id": "existing-track-id"}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    track_id = repo.upsert_imported_track(
        user_id="u-1",
        spotify_id="spt-abc",
        title="X", isrc=None, length_ms=200_000, now=_utc(),
    )
    assert track_id == "existing-track-id"


def test_upsert_imported_track_inserts_new_when_missing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    calls = []

    def _execute(sql, params=None, transaction_id=None):
        calls.append(sql.split("\n")[0].strip())
        if "SELECT id FROM clouder_tracks WHERE spotify_id" in sql:
            return []
        if "INSERT INTO clouder_tracks" in sql:
            return [{"id": params["id"]}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    track_id = repo.upsert_imported_track(
        user_id="u-1",
        spotify_id="spt-abc",
        title="X", isrc=None, length_ms=None, now=_utc(),
    )
    assert track_id  # something non-empty
    assert any("INSERT INTO clouder_tracks" in c for c in calls)
    assert any("INSERT INTO user_imported_tracks" in c for c in calls)


def test_upsert_imported_track_handles_race_on_conflict() -> None:
    """ON CONFLICT skipped → repository re-SELECTs the winner's id."""
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    state = {"selected": 0}

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT id FROM clouder_tracks WHERE spotify_id" in sql:
            state["selected"] += 1
            if state["selected"] == 1:
                return []  # first check: not there
            return [{"id": "winner"}]  # second check after ON CONFLICT
        if "INSERT INTO clouder_tracks" in sql:
            return []  # conflict, nothing returned
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    track_id = repo.upsert_imported_track(
        user_id="u-1",
        spotify_id="spt-abc",
        title="X", isrc=None, length_ms=None, now=_utc(),
    )
    assert track_id == "winner"
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_playlists_repository.py -q`

- [ ] **Step 3: Add methods**

Append to `playlists_repository.py`:

```python
import uuid


_SCOPE_CHECK_SQL = """
    SELECT t.id
    FROM clouder_tracks t
    WHERE t.id = ANY(:track_ids)
      AND (
        EXISTS (
          SELECT 1 FROM category_tracks ct
          JOIN categories c ON c.id = ct.category_id
          WHERE ct.track_id = t.id AND c.user_id = :user_id
        )
        OR EXISTS (
          SELECT 1 FROM playlist_tracks pt
          JOIN playlists p ON p.id = pt.playlist_id
          WHERE pt.track_id = t.id
            AND p.user_id = :user_id
            AND p.deleted_at IS NULL
        )
        OR EXISTS (
          SELECT 1 FROM user_imported_tracks uit
          WHERE uit.track_id = t.id AND uit.user_id = :user_id
        )
      )
"""


class PlaylistsRepository:
    # ... existing ...

    def validate_tracks_in_scope(
        self,
        *,
        user_id: str,
        track_ids: list[str],
    ) -> set[str]:
        if not track_ids:
            return set()
        rows = self._data_api.execute(
            _SCOPE_CHECK_SQL,
            {"user_id": user_id, "track_ids": track_ids},
        )
        return {r["id"] for r in rows}

    def upsert_imported_track(
        self,
        *,
        user_id: str,
        spotify_id: str,
        title: str,
        isrc: str | None,
        length_ms: int | None,
        now: datetime,
    ) -> str:
        """Idempotent import: returns canonical clouder_tracks.id.

        Three branches:
          1. spotify_id already present → reuse.
          2. INSERT ... ON CONFLICT DO NOTHING returned a row → use it.
          3. Conflict (race) → re-SELECT to find the winner's id.

        Always inserts a (user_id, track_id) marker into user_imported_tracks.
        """
        with self._data_api.transaction() as tx_id:
            existing = self._data_api.execute(
                "SELECT id FROM clouder_tracks WHERE spotify_id = :spotify_id",
                {"spotify_id": spotify_id},
                transaction_id=tx_id,
            )
            if existing:
                track_id = existing[0]["id"]
            else:
                new_id = str(uuid.uuid4())
                inserted = self._data_api.execute(
                    """
                    INSERT INTO clouder_tracks (
                        id, title, isrc, length_ms, spotify_id, origin,
                        first_seen_at
                    ) VALUES (
                        :id, :title, :isrc, :length_ms, :spotify_id,
                        'spotify_user_import', :now
                    )
                    ON CONFLICT (spotify_id) DO NOTHING
                    RETURNING id
                    """,
                    {
                        "id": new_id,
                        "title": title,
                        "isrc": isrc,
                        "length_ms": length_ms,
                        "spotify_id": spotify_id,
                        "now": now,
                    },
                    transaction_id=tx_id,
                )
                if inserted:
                    track_id = inserted[0]["id"]
                else:
                    rerun = self._data_api.execute(
                        "SELECT id FROM clouder_tracks WHERE spotify_id = :spotify_id",
                        {"spotify_id": spotify_id},
                        transaction_id=tx_id,
                    )
                    track_id = rerun[0]["id"]

            self._data_api.execute(
                """
                INSERT INTO user_imported_tracks (user_id, track_id, imported_at)
                VALUES (:user_id, :track_id, :now)
                ON CONFLICT DO NOTHING
                """,
                {"user_id": user_id, "track_id": track_id, "now": now},
                transaction_id=tx_id,
            )
            return track_id
```

> **Note:** `clouder_tracks` has other NOT NULL columns. Inspect `db_models.py` first; if there are required columns not covered above (e.g. `created_at`), extend the INSERT before running the test. Set them to `:now` or a sensible NULL-safe default. The migration in Task 1 did not change those — they're whatever the existing schema mandates.

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_playlists_repository.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py \
        tests/unit/test_playlists_repository.py
git commit -m "$(cat <<'EOF'
feat(playlists): scope check + idempotent Spotify import upsert

validate_tracks_in_scope returns the user-visible subset across
categories, own playlists, and prior imports. upsert_imported_track
handles the race with ON CONFLICT then re-SELECT for the winning
canonical id, and always records the user_imported_tracks marker.
EOF
)"
```

---

## Task 8: Spotify token resolver

**Files:**

- Create: `src/collector/curation/spotify_token_resolver.py`
- Test: `tests/unit/test_spotify_token_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_spotify_token_resolver.py`:

```python
"""Resolver reads + KMS-decrypts user_vendor_tokens.spotify, refreshing
when expiry is within 60s."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import SpotifyNotAuthorizedError
from collector.curation.spotify_token_resolver import (
    ResolvedSpotifyToken,
    SpotifyTokenResolver,
)


def _utc(offset_s: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=offset_s)


def test_returns_existing_token_when_not_near_expiry() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": b"enc-a",
        "refresh_token_enc": b"enc-r",
        "data_key_enc": b"dk",
        "expires_at": _utc(3600).isoformat(),
    }]
    envelope = MagicMock()
    envelope.decrypt.return_value = b"access-plain"
    oauth = MagicMock()

    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    result = resolver.resolve(user_id="u-1")
    assert isinstance(result, ResolvedSpotifyToken)
    assert result.access_token == "access-plain"
    oauth.refresh.assert_not_called()


def test_refreshes_when_within_60s_of_expiry() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": b"enc-a",
        "refresh_token_enc": b"enc-r",
        "data_key_enc": b"dk",
        "expires_at": _utc(30).isoformat(),
    }]
    envelope = MagicMock()
    envelope.decrypt.side_effect = [b"refresh-plain", b"new-access"]
    envelope.encrypt.side_effect = [
        MagicMock(serialize=lambda: b"new-enc-a"),
        MagicMock(serialize=lambda: b"new-enc-r"),
    ]
    oauth = MagicMock()
    new_tokens = MagicMock(
        access_token="new-access", refresh_token="new-refresh",
        expires_in=3600,
    )
    oauth.refresh.return_value = new_tokens

    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    result = resolver.resolve(user_id="u-1")
    assert result.access_token == "new-access"
    oauth.refresh.assert_called_once_with(refresh_token="refresh-plain")
    # UPDATE was written
    update_calls = [
        c for c in data_api.execute.call_args_list
        if "UPDATE user_vendor_tokens" in c[0][0]
    ]
    assert len(update_calls) == 1


def test_raises_not_authorized_when_no_token_row() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = []
    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=MagicMock(), oauth_client=MagicMock(),
    )
    with pytest.raises(SpotifyNotAuthorizedError):
        resolver.resolve(user_id="u-1")


def test_raises_not_authorized_when_refresh_fails() -> None:
    data_api = MagicMock()
    data_api.execute.return_value = [{
        "access_token_enc": b"enc-a",
        "refresh_token_enc": b"enc-r",
        "data_key_enc": b"dk",
        "expires_at": _utc(0).isoformat(),
    }]
    envelope = MagicMock()
    envelope.decrypt.return_value = b"refresh-plain"
    oauth = MagicMock()

    class _Boom(Exception):
        pass

    oauth.refresh.side_effect = _Boom("invalid_grant")

    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    with pytest.raises(SpotifyNotAuthorizedError):
        resolver.resolve(user_id="u-1")
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_spotify_token_resolver.py -q`

- [ ] **Step 3: Implement resolver**

Create `src/collector/curation/spotify_token_resolver.py`:

```python
"""Read + KMS-decrypt + refresh the user's Spotify OAuth access token.

Storage shape comes from auth_repository / user_vendor_tokens (vendor='spotify').
This module is *only* the read+refresh path used at playlist publish/import
time. Initial OAuth + replay protection still lives in auth_handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from collector.auth.kms_envelope import EnvelopePayload, KmsEnvelope
from collector.data_api import DataAPIClient
from collector.logging_utils import log_event

from . import SpotifyNotAuthorizedError


_REFRESH_LEEWAY_SECONDS = 60


@dataclass(frozen=True)
class ResolvedSpotifyToken:
    user_id: str
    access_token: str
    refreshed: bool


class _OAuthClientLike(Protocol):
    def refresh(self, *, refresh_token: str) -> Any: ...


def _parse_expires_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace(" ", "T")
    if "+" not in s and "Z" not in s:
        s = s + "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class SpotifyTokenResolver:
    def __init__(
        self,
        *,
        data_api: DataAPIClient,
        envelope: KmsEnvelope,
        oauth_client: _OAuthClientLike,
    ) -> None:
        self._data_api = data_api
        self._envelope = envelope
        self._oauth = oauth_client

    def resolve(self, *, user_id: str) -> ResolvedSpotifyToken:
        rows = self._data_api.execute(
            """
            SELECT access_token_enc, refresh_token_enc,
                   data_key_enc, expires_at
            FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = 'spotify'
            """,
            {"user_id": user_id},
        )
        if not rows:
            raise SpotifyNotAuthorizedError(
                f"No Spotify token on file for user {user_id}"
            )
        row = rows[0]
        expires_at = _parse_expires_at(row["expires_at"])
        now = datetime.now(timezone.utc)

        if (expires_at - now).total_seconds() > _REFRESH_LEEWAY_SECONDS:
            plain = self._envelope.decrypt(row["access_token_enc"])
            return ResolvedSpotifyToken(
                user_id=user_id,
                access_token=plain.decode("utf-8"),
                refreshed=False,
            )

        # Refresh path.
        try:
            refresh_plain = self._envelope.decrypt(
                row["refresh_token_enc"]
            ).decode("utf-8")
            new_tokens = self._oauth.refresh(refresh_token=refresh_plain)
        except Exception as exc:
            raise SpotifyNotAuthorizedError(
                "Spotify refresh failed"
            ) from exc

        access_payload = self._envelope.encrypt(
            new_tokens.access_token.encode("utf-8")
        )
        refresh_payload = self._envelope.encrypt(
            new_tokens.refresh_token.encode("utf-8")
        )
        new_expires = now + timedelta(seconds=int(new_tokens.expires_in))

        self._data_api.execute(
            """
            UPDATE user_vendor_tokens SET
                access_token_enc = :access_enc,
                refresh_token_enc = :refresh_enc,
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE user_id = :user_id AND vendor = 'spotify'
            """,
            {
                "user_id": user_id,
                "access_enc": access_payload.serialize(),
                "refresh_enc": refresh_payload.serialize(),
                "expires_at": new_expires,
                "updated_at": now,
            },
        )
        log_event(
            "INFO",
            "playlist_publish_token_refreshed",
            user_id=user_id,
        )
        return ResolvedSpotifyToken(
            user_id=user_id,
            access_token=new_tokens.access_token,
            refreshed=True,
        )
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_spotify_token_resolver.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/spotify_token_resolver.py \
        tests/unit/test_spotify_token_resolver.py
git commit -m "$(cat <<'EOF'
feat(playlists): Spotify token resolver

Reads user_vendor_tokens.spotify, KMS-decrypts, and refreshes when
within 60s of expiry. Refresh failure maps to SpotifyNotAuthorized
so the publish handler returns 412 and the SPA can prompt re-login.
EOF
)"
```

---

## Task 9: Spotify user client (HTTP)

**Files:**

- Create: `src/collector/curation/spotify_user_client.py`
- Test: `tests/unit/test_spotify_user_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_spotify_user_client.py`:

```python
"""HTTP-shaped unit tests for the user-OAuth Spotify Web API client.

`requests` is stubbed via a simple fake session that records calls and
returns canned responses. No network."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from collector.curation import (
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyRateLimitedError,
    SpotifyScopeInsufficientError,
)
from collector.curation.spotify_user_client import (
    SpotifyTrackPayload,
    SpotifyUserClient,
    SpotifyPlaylistRef,
)


class _Resp:
    def __init__(self, status_code: int, body: dict | None = None,
                 headers: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._body


def _client(session: MagicMock, sleep=lambda _s: None) -> SpotifyUserClient:
    return SpotifyUserClient(
        access_token="tok", session=session, sleep=sleep,
    )


def test_get_track_returns_payload() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(200, {
        "id": "spt-abc", "name": "Track A",
        "duration_ms": 180000, "external_ids": {"isrc": "ISRC1"},
        "artists": [{"id": "art-1", "name": "Art One"}],
    })
    client = _client(session)
    track = client.get_track("spt-abc")
    assert isinstance(track, SpotifyTrackPayload)
    assert track.id == "spt-abc"
    assert track.isrc == "ISRC1"
    assert track.artists[0].name == "Art One"


def test_create_playlist_posts_and_returns_ref() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(201, {
        "id": "pl-1",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl-1"},
    })
    client = _client(session)
    ref = client.create_playlist(
        user_spotify_id="user-1", name="My Set",
        description="desc", public=False,
    )
    assert isinstance(ref, SpotifyPlaylistRef)
    assert ref.id == "pl-1"
    assert ref.url == "https://open.spotify.com/playlist/pl-1"


def test_429_with_retry_after_retries_then_succeeds() -> None:
    session = MagicMock()
    session.request.side_effect = [
        _Resp(429, headers={"Retry-After": "0"}),
        _Resp(200, {"id": "x", "name": "n", "duration_ms": 0,
                    "external_ids": {}, "artists": []}),
    ]
    slept: list[float] = []
    client = _client(session, sleep=lambda s: slept.append(s))
    client.get_track("x")
    assert slept and slept[0] == 0.0


def test_429_persistent_raises_rate_limited() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(429, headers={"Retry-After": "0"})
    client = _client(session, sleep=lambda _: None)
    with pytest.raises(SpotifyRateLimitedError):
        client.get_track("x")


def test_5xx_retries_once_then_raises() -> None:
    session = MagicMock()
    session.request.side_effect = [
        _Resp(503),
        _Resp(503),
    ]
    client = _client(session, sleep=lambda _: None)
    with pytest.raises(SpotifyApiError):
        client.get_track("x")


def test_401_propagates_as_not_authorized() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(401, {"error": "expired"})
    client = _client(session)
    with pytest.raises(SpotifyNotAuthorizedError):
        client.get_track("x")


def test_403_insufficient_scope_propagates() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(
        403, {"error": {"message": "Insufficient client scope"}},
    )
    client = _client(session)
    with pytest.raises(SpotifyScopeInsufficientError):
        client.set_cover("pl-1", b"jpeg-bytes")


def test_replace_tracks_uses_put() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(200, {})
    client = _client(session)
    client.replace_tracks("pl-1", ["spotify:track:a", "spotify:track:b"])
    args, kwargs = session.request.call_args
    assert kwargs["method"] == "PUT" or args[0] == "PUT"
    assert "playlists/pl-1/tracks" in (kwargs.get("url") or args[1])


def test_append_tracks_uses_post() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(201, {})
    client = _client(session)
    client.append_tracks("pl-1", ["spotify:track:c"])
    args, kwargs = session.request.call_args
    method = kwargs.get("method") or args[0]
    assert method == "POST"


def test_set_cover_base64_encodes_and_sends() -> None:
    session = MagicMock()
    session.request.return_value = _Resp(202)
    client = _client(session)
    client.set_cover("pl-1", b"\xff\xd8\xff\xe0jpeg-bytes")
    _, kwargs = session.request.call_args
    body = kwargs.get("data")
    assert isinstance(body, (bytes, str))
    # base64-encoded JPEG bytes start with /9j when source is JPEG
    assert b"/9j" in (body if isinstance(body, bytes) else body.encode())
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_spotify_user_client.py -q`

- [ ] **Step 3: Implement client**

Create `src/collector/curation/spotify_user_client.py`:

```python
"""User-OAuth Spotify Web API client (playlist publish, import).

Distinct from collector.spotify_client which uses client_credentials.
Retry policy: 429 → respect Retry-After once; 5xx → 1 retry; 401 → no
retry, surfaces as SpotifyNotAuthorizedError; 403 with
'insufficient_scope' → SpotifyScopeInsufficientError.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from . import (
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyRateLimitedError,
    SpotifyScopeInsufficientError,
)


_BASE = "https://api.spotify.com/v1"
_MAX_RETRIES_429 = 1
_MAX_RETRIES_5XX = 1


@dataclass(frozen=True)
class SpotifyArtistRef:
    id: str
    name: str
    spotify_id: str | None = None


@dataclass(frozen=True)
class SpotifyTrackPayload:
    id: str
    name: str
    duration_ms: int | None
    isrc: str | None
    artists: tuple[SpotifyArtistRef, ...]


@dataclass(frozen=True)
class SpotifyPlaylistRef:
    id: str
    url: str | None


class SpotifyUserClient:
    def __init__(
        self,
        *,
        access_token: str,
        session: Any,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._access_token = access_token
        self._session = session
        self._sleep = sleep or (lambda s: None)

    # ---------- Public methods ----------------------------------------------

    def get_track(self, spotify_id: str) -> SpotifyTrackPayload:
        body = self._request("GET", f"{_BASE}/tracks/{spotify_id}")
        return SpotifyTrackPayload(
            id=body["id"],
            name=body["name"],
            duration_ms=body.get("duration_ms"),
            isrc=(body.get("external_ids") or {}).get("isrc"),
            artists=tuple(
                SpotifyArtistRef(
                    id=a.get("id") or "",
                    name=a.get("name") or "",
                    spotify_id=a.get("id"),
                )
                for a in (body.get("artists") or [])
            ),
        )

    def create_playlist(
        self,
        *,
        user_spotify_id: str,
        name: str,
        description: str | None,
        public: bool,
    ) -> SpotifyPlaylistRef:
        body = self._request(
            "POST",
            f"{_BASE}/users/{user_spotify_id}/playlists",
            json_body={
                "name": name,
                "description": description or "",
                "public": public,
            },
        )
        return SpotifyPlaylistRef(
            id=body["id"],
            url=(body.get("external_urls") or {}).get("spotify"),
        )

    def update_playlist(
        self,
        *,
        spotify_playlist_id: str,
        name: str,
        description: str | None,
        public: bool,
    ) -> None:
        self._request(
            "PUT",
            f"{_BASE}/playlists/{spotify_playlist_id}",
            json_body={
                "name": name,
                "description": description or "",
                "public": public,
            },
        )

    def replace_tracks(
        self, spotify_playlist_id: str, uris: list[str]
    ) -> None:
        self._request(
            "PUT",
            f"{_BASE}/playlists/{spotify_playlist_id}/tracks",
            json_body={"uris": uris},
        )

    def append_tracks(
        self, spotify_playlist_id: str, uris: list[str]
    ) -> None:
        if not uris:
            return
        self._request(
            "POST",
            f"{_BASE}/playlists/{spotify_playlist_id}/tracks",
            json_body={"uris": uris},
        )

    def set_cover(self, spotify_playlist_id: str, jpeg_bytes: bytes) -> None:
        encoded = base64.b64encode(jpeg_bytes)
        self._request(
            "PUT",
            f"{_BASE}/playlists/{spotify_playlist_id}/images",
            data=encoded,
            content_type="image/jpeg",
        )

    # ---------- Core HTTP w/ retry ------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict | None = None,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": content_type,
        }
        body: Any = None
        if json_body is not None:
            body = json.dumps(json_body)
        elif data is not None:
            body = data

        attempts_429 = 0
        attempts_5xx = 0
        last_resp = None
        while True:
            resp = self._session.request(
                method=method, url=url, headers=headers, data=body,
            )
            last_resp = resp
            status = getattr(resp, "status_code", 0)
            if 200 <= status < 300:
                try:
                    return resp.json()
                except Exception:
                    return {}
            if status == 401:
                raise SpotifyNotAuthorizedError("Spotify returned 401")
            if status == 403:
                msg = ""
                try:
                    err = resp.json().get("error") or {}
                    msg = err.get("message", "") if isinstance(err, dict) else ""
                except Exception:
                    pass
                if "scope" in msg.lower():
                    raise SpotifyScopeInsufficientError(msg or "Insufficient scope")
                raise SpotifyApiError(f"Spotify 403: {msg or 'forbidden'}")
            if status == 429:
                if attempts_429 >= _MAX_RETRIES_429:
                    raise SpotifyRateLimitedError("Spotify rate limit persists")
                retry_after = float(
                    (resp.headers or {}).get("Retry-After") or "0.0"
                )
                self._sleep(retry_after)
                attempts_429 += 1
                continue
            if 500 <= status < 600:
                if attempts_5xx >= _MAX_RETRIES_5XX:
                    raise SpotifyApiError(f"Spotify {status}")
                self._sleep(0.5)
                attempts_5xx += 1
                continue
            raise SpotifyApiError(
                f"Spotify {status}: unexpected response"
            )
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_spotify_user_client.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/spotify_user_client.py \
        tests/unit/test_spotify_user_client.py
git commit -m "$(cat <<'EOF'
feat(playlists): Spotify user-OAuth API client

get_track / create_playlist / update_playlist / replace_tracks /
append_tracks / set_cover. Retry policy: 429 once (Retry-After),
5xx once, 401 → SpotifyNotAuthorized, 403 with scope keyword →
SpotifyScopeInsufficient.
EOF
)"
```

---

## Task 10: Storage — cover presign helpers

**Files:**

- Modify: `src/collector/storage.py`
- Test: `tests/unit/test_storage_covers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_storage_covers.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from collector.errors import StorageError
from collector.storage import S3Storage


def _storage(client: MagicMock) -> S3Storage:
    return S3Storage(s3_client=client, bucket_name="b", raw_prefix="raw/bp/releases")


def test_cover_put_key_uses_user_playlist_epoch() -> None:
    s = _storage(MagicMock())
    key = s.cover_key(user_id="u-1", playlist_id="p-1", epoch_ms=1234567890)
    assert key == "covers/u-1/p-1/1234567890.jpg"


def test_presigned_put_url_calls_s3_generate() -> None:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed-put"
    s = _storage(client)
    url = s.presigned_cover_put_url(
        s3_key="covers/u/p/1.jpg",
        max_bytes=262144,
        expires_in=300,
    )
    assert url == "https://signed-put"
    args, kwargs = client.generate_presigned_url.call_args
    assert args[0] == "put_object"
    params = kwargs.get("Params") or args[1]
    assert params["Bucket"] == "b"
    assert params["Key"] == "covers/u/p/1.jpg"
    assert params["ContentType"] == "image/jpeg"


def test_presigned_get_url() -> None:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed-get"
    s = _storage(client)
    url = s.presigned_cover_get_url(
        s3_key="covers/u/p/1.jpg", expires_in=3600,
    )
    assert url == "https://signed-get"


def test_head_cover_returns_size_when_present() -> None:
    client = MagicMock()
    client.head_object.return_value = {
        "ContentLength": 12345, "ContentType": "image/jpeg",
    }
    s = _storage(client)
    info = s.head_cover("covers/u/p/1.jpg")
    assert info == {"size": 12345, "content_type": "image/jpeg"}


def test_head_cover_returns_none_when_404() -> None:
    client = MagicMock()
    class _NoSuch(Exception):
        pass
    err = _NoSuch("NoSuchKey")
    setattr(err, "response", {"Error": {"Code": "NoSuchKey"}})
    client.head_object.side_effect = err
    s = _storage(client)
    assert s.head_cover("covers/u/p/1.jpg") is None


def test_read_cover_bytes_returns_payload() -> None:
    client = MagicMock()
    stream = MagicMock()
    stream.read.return_value = b"jpeg-bytes"
    client.get_object.return_value = {"Body": stream}
    s = _storage(client)
    out = s.read_cover_bytes("covers/u/p/1.jpg")
    assert out == b"jpeg-bytes"


def test_read_cover_bytes_raises_storage_error_on_failure() -> None:
    client = MagicMock()
    client.get_object.side_effect = RuntimeError("S3 boom")
    s = _storage(client)
    with pytest.raises(StorageError):
        s.read_cover_bytes("covers/u/p/1.jpg")
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_storage_covers.py -q`

- [ ] **Step 3: Extend `storage.py`**

Add methods to `S3Storage` class in `src/collector/storage.py`:

```python
    # ---------- Cover support (spec 2026-05-11) ------------------------------

    @staticmethod
    def cover_key(*, user_id: str, playlist_id: str, epoch_ms: int) -> str:
        return f"covers/{user_id}/{playlist_id}/{epoch_ms}.jpg"

    def presigned_cover_put_url(
        self,
        *,
        s3_key: str,
        max_bytes: int,
        expires_in: int = 300,
    ) -> str:
        return self.s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": s3_key,
                "ContentType": "image/jpeg",
                "ContentLength": max_bytes,
            },
            ExpiresIn=expires_in,
        )

    def presigned_cover_get_url(
        self,
        *,
        s3_key: str,
        expires_in: int = 3600,
    ) -> str:
        return self.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    def head_cover(self, s3_key: str) -> dict | None:
        try:
            head = self.s3_client.head_object(
                Bucket=self.bucket_name, Key=s3_key,
            )
        except Exception as exc:
            code = ""
            response = getattr(exc, "response", None)
            if isinstance(response, dict):
                code = (response.get("Error") or {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                return None
            raise StorageError(f"Failed to HEAD cover: {s3_key}") from exc
        return {
            "size": int(head["ContentLength"]),
            "content_type": head.get("ContentType") or "",
        }

    def read_cover_bytes(self, s3_key: str) -> bytes:
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=s3_key,
            )
            return response["Body"].read()
        except Exception as exc:
            raise StorageError(f"Failed to read cover: {s3_key}") from exc
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_storage_covers.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/storage.py tests/unit/test_storage_covers.py
git commit -m "$(cat <<'EOF'
feat(playlists): S3 cover helpers

cover_key/{put,get}_url/head/read for covers/{user}/{playlist}/{epoch}.jpg.
Versioned key acts as cache buster — new upload yields a fresh URL.
EOF
)"
```

---

## Task 11: Pydantic schemas

**Files:**

- Modify: `src/collector/curation/schemas.py`
- Test: `tests/unit/test_playlists_schemas.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_playlists_schemas.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from collector.curation.schemas import (
    AddTracksIn,
    CoverUploadUrlIn,
    CreatePlaylistIn,
    ImportSpotifyTracksIn,
    PatchPlaylistIn,
    PublishPlaylistIn,
    ReorderPlaylistTracksIn,
)


def test_create_playlist_minimum() -> None:
    body = CreatePlaylistIn.model_validate({"name": "My Set"})
    assert body.description is None
    assert body.is_public is False


def test_create_playlist_full() -> None:
    body = CreatePlaylistIn.model_validate({
        "name": "S", "description": "d", "is_public": True,
    })
    assert body.is_public is True


def test_create_playlist_rejects_blank_name() -> None:
    with pytest.raises(PydanticValidationError):
        CreatePlaylistIn.model_validate({"name": ""})


def test_create_playlist_rejects_extra_fields() -> None:
    with pytest.raises(PydanticValidationError):
        CreatePlaylistIn.model_validate({"name": "x", "foo": 1})


def test_patch_playlist_allows_partial() -> None:
    body = PatchPlaylistIn.model_validate({"is_public": True})
    assert body.name is None
    assert body.description is None
    assert body.is_public is True


def test_patch_playlist_requires_at_least_one_field() -> None:
    with pytest.raises(PydanticValidationError):
        PatchPlaylistIn.model_validate({})


def test_add_tracks_in_requires_non_empty() -> None:
    with pytest.raises(PydanticValidationError):
        AddTracksIn.model_validate({"track_ids": []})


def test_add_tracks_in_caps_size() -> None:
    with pytest.raises(PydanticValidationError):
        AddTracksIn.model_validate({"track_ids": ["x"] * 1001})


def test_reorder_accepts_list() -> None:
    body = ReorderPlaylistTracksIn.model_validate(
        {"track_ids": ["a", "b"]}
    )
    assert body.track_ids == ["a", "b"]


def test_import_spotify_caps_at_50() -> None:
    with pytest.raises(PydanticValidationError):
        ImportSpotifyTracksIn.model_validate(
            {"spotify_refs": ["x"] * 51},
        )


def test_publish_in_requires_confirm_overwrite_bool() -> None:
    body = PublishPlaylistIn.model_validate({"confirm_overwrite": True})
    assert body.confirm_overwrite is True


def test_publish_in_defaults_confirm_to_false() -> None:
    body = PublishPlaylistIn.model_validate({})
    assert body.confirm_overwrite is False


def test_cover_upload_url_in_requires_jpeg() -> None:
    body = CoverUploadUrlIn.model_validate({"content_type": "image/jpeg"})
    assert body.content_type == "image/jpeg"


def test_cover_upload_url_rejects_other_types() -> None:
    with pytest.raises(PydanticValidationError):
        CoverUploadUrlIn.model_validate({"content_type": "image/png"})
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_playlists_schemas.py -q`

- [ ] **Step 3: Add schemas**

Append to `src/collector/curation/schemas.py`:

```python
# ----------------------- Playlists (spec 2026-05-11) -----------------------


class CreatePlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    is_public: bool = False


class PatchPlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    is_public: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "PatchPlaylistIn":
        if self.name is None and self.description is None and self.is_public is None:
            raise ValueError("At least one of name/description/is_public must be set")
        return self


class AddTracksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_ids: list[str] = Field(..., min_length=1, max_length=1000)


class ReorderPlaylistTracksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_ids: list[str]


class ImportSpotifyTracksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spotify_refs: list[str] = Field(..., min_length=1, max_length=50)


class PublishPlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_overwrite: bool = False


class CoverUploadUrlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_type: str = Field(..., pattern=r"^image/jpeg$")
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_playlists_schemas.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/schemas.py tests/unit/test_playlists_schemas.py
git commit -m "$(cat <<'EOF'
feat(playlists): pydantic request schemas

CreatePlaylistIn/PatchPlaylistIn/AddTracksIn/ReorderPlaylistTracksIn/
ImportSpotifyTracksIn/PublishPlaylistIn/CoverUploadUrlIn. Patch
requires at least one field. Cover restricted to image/jpeg.
EOF
)"
```

---

## Task 12: Handler — CRUD routes wired into route table

**Files:**

- Modify: `src/collector/curation_handler.py`
- Test: `tests/unit/test_curation_handler_playlists.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_curation_handler_playlists.py`:

```python
"""Handler-level smoke tests for /playlists routes. Repository is a stub."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from collector.curation_handler import lambda_handler


def _event(method: str, path: str, body: dict | None = None,
           path_params: dict | None = None) -> dict:
    return {
        "requestContext": {
            "routeKey": f"{method} {path}",
            "authorizer": {"lambda": {"user_id": "u-1"}},
        },
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else "",
        "headers": {"x-correlation-id": "cid-1"},
    }


def _patch_factory(repo: MagicMock):
    return patch(
        "collector.curation_handler.create_default_playlists_repository",
        return_value=repo,
    )


def test_create_playlist_returns_201() -> None:
    repo = MagicMock()
    repo.create.return_value = MagicMock(
        id="p-1", user_id="u-1", name="My Set", normalized_name="my set",
        description=None, is_public=False, cover_s3_key=None,
        cover_uploaded_at=None, spotify_playlist_id=None,
        last_published_at=None, needs_republish=False, track_count=0,
        created_at="2026-05-12T10:00:00+00:00",
        updated_at="2026-05-12T10:00:00+00:00",
    )
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists", {"name": "My Set"}),
            None,
        )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["id"] == "p-1"


def test_get_playlist_returns_404_when_missing() -> None:
    repo = MagicMock()
    repo.get.return_value = None
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("GET", "/playlists/{id}", path_params={"id": "missing"}),
            None,
        )
    assert resp["statusCode"] == 404


def test_patch_playlist_returns_200() -> None:
    repo = MagicMock()
    repo.patch.return_value = MagicMock(
        id="p-1", user_id="u-1", name="renamed", normalized_name="renamed",
        description=None, is_public=False, cover_s3_key=None,
        cover_uploaded_at=None, spotify_playlist_id=None,
        last_published_at=None, needs_republish=False, track_count=0,
        created_at="2026-05-12T10:00:00+00:00",
        updated_at="2026-05-12T10:00:00+00:00",
    )
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("PATCH", "/playlists/{id}",
                   body={"name": "renamed"},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200


def test_delete_playlist_returns_204() -> None:
    repo = MagicMock()
    repo.soft_delete.return_value = True
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("DELETE", "/playlists/{id}", path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 204


def test_list_playlists_paginated() -> None:
    repo = MagicMock()
    repo.list_all.return_value = ([], 0)
    with _patch_factory(repo):
        resp = lambda_handler(_event("GET", "/playlists"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["items"] == []
    assert body["total"] == 0
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_curation_handler_playlists.py -q`

- [ ] **Step 3: Add handlers + register routes**

In `src/collector/curation_handler.py`:

1. **Imports — add** to the existing `from .curation import (...)` block:

```python
    ConfirmOverwriteRequiredError,
    CoverMissingError,
    CoverTooLargeError,
    InvalidSpotifyRefError,
    NothingToPublishError,
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
    PlaylistTrackLimitError,
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyRateLimitedError,
    SpotifyScopeInsufficientError,
    TrackNotInUserScopeError,
```

2. **New imports** below existing curation submodule imports:

```python
from .curation.playlists_repository import (
    PlaylistsRepository,
    create_default_playlists_repository,
)
from .curation.playlists_service import (
    MAX_IMPORT_REFS_PER_REQUEST,
    normalize_playlist_name,
    parse_spotify_ref,
    validate_description,
    validate_playlist_name,
)
from .curation.schemas import (
    AddTracksIn,
    CoverUploadUrlIn,
    CreatePlaylistIn,
    ImportSpotifyTracksIn,
    PatchPlaylistIn,
    PublishPlaylistIn,
    ReorderPlaylistTracksIn,
)
```

3. **Add a JSON serializer** for playlist rows (next to `_category_response`):

```python
def _playlist_response(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "description": row.description,
        "is_public": row.is_public,
        "cover_s3_key": row.cover_s3_key,
        "cover_uploaded_at": row.cover_uploaded_at,
        "spotify_playlist_id": row.spotify_playlist_id,
        "last_published_at": row.last_published_at,
        "needs_republish": row.needs_republish,
        "track_count": row.track_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
```

4. **Add CRUD handlers** (near the existing categories handlers):

```python
def _handle_create_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    body = CreatePlaylistIn.model_validate(_parse_body(event))
    validate_playlist_name(body.name)
    validate_description(body.description)
    normalized = normalize_playlist_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    playlist_id = str(uuid.uuid4())
    row = repo.create(
        user_id=user_id,
        playlist_id=playlist_id,
        name=body.name.strip(),
        normalized_name=normalized,
        description=body.description,
        is_public=body.is_public,
        now=utc_now(),
    )
    log_event("INFO", "playlist_created",
              correlation_id=correlation_id, user_id=user_id, playlist_id=row.id)
    payload = _playlist_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(201, payload, correlation_id)


def _handle_list_playlists(event, repo: PlaylistsRepository, user_id, correlation_id):
    limit, offset = _parse_pagination(event)
    rows, total = repo.list_all(user_id=user_id, limit=limit, offset=offset)
    return _json_response(
        200,
        {
            "items": [_playlist_response(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_get_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    row = repo.get(user_id=user_id, playlist_id=pid)
    if row is None:
        raise PlaylistNotFoundError()
    payload = _playlist_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_patch_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = PatchPlaylistIn.model_validate(_parse_body(event))
    name = body.name.strip() if body.name is not None else None
    normalized = normalize_playlist_name(body.name) if body.name is not None else None
    if body.name is not None:
        validate_playlist_name(body.name)
    if body.description is not None:
        validate_description(body.description)
    row = repo.patch(
        user_id=user_id, playlist_id=pid,
        name=name, normalized_name=normalized,
        description=body.description, is_public=body.is_public,
        now=utc_now(),
    )
    log_event("INFO", "playlist_patched",
              correlation_id=correlation_id, user_id=user_id, playlist_id=pid)
    payload = _playlist_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_delete_playlist(event, repo: PlaylistsRepository, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    ok = repo.soft_delete(user_id=user_id, playlist_id=pid, now=utc_now())
    if not ok:
        raise PlaylistNotFoundError()
    log_event("INFO", "playlist_deleted",
              correlation_id=correlation_id, user_id=user_id, playlist_id=pid)
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }
```

5. **Register a factory** above `_ROUTE_TABLE`:

```python
def _playlists_factory() -> Any:
    return create_default_playlists_repository()
```

6. **Append routes** at the end of `_ROUTE_TABLE`:

```python
    "POST /playlists": (_handle_create_playlist, _playlists_factory),
    "GET /playlists": (_handle_list_playlists, _playlists_factory),
    "GET /playlists/{id}": (_handle_get_playlist, _playlists_factory),
    "PATCH /playlists/{id}": (_handle_patch_playlist, _playlists_factory),
    "DELETE /playlists/{id}": (_handle_delete_playlist, _playlists_factory),
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_curation_handler_playlists.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_handler_playlists.py
git commit -m "$(cat <<'EOF'
feat(playlists): handler CRUD routes

POST/GET/PATCH/DELETE /playlists + GET /playlists/{id}. Reuses
existing JWT context + error envelope. Factory pattern mirrors
categories/tags so the route table stays the only routing source.
EOF
)"
```

---

## Task 13: Handler — tracks routes (add / remove / list / reorder)

**Files:**

- Modify: `src/collector/curation_handler.py`
- Modify: `tests/unit/test_curation_handler_playlists.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_curation_handler_playlists.py`:

```python
def test_list_playlist_tracks_returns_paginated() -> None:
    repo = MagicMock()
    repo.list_tracks.return_value = ([], 0)
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("GET", "/playlists/{id}/tracks",
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200


def test_add_tracks_resolves_scope_then_appends() -> None:
    repo = MagicMock()
    repo.validate_tracks_in_scope.return_value = {"t-1", "t-2"}
    repo.append_tracks.return_value = MagicMock(
        added_track_ids=["t-1", "t-2"],
        skipped_duplicates=[],
        position_after=2,
    )
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/tracks",
                   body={"track_ids": ["t-1", "t-2"]},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["added"] == ["t-1", "t-2"]
    assert body["position_after"] == 2


def test_add_tracks_returns_404_for_out_of_scope() -> None:
    repo = MagicMock()
    repo.validate_tracks_in_scope.return_value = {"t-1"}
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/tracks",
                   body={"track_ids": ["t-1", "t-foreign"]},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "t-foreign" in body["missing_track_ids"]


def test_remove_track_204() -> None:
    repo = MagicMock()
    repo.remove_track.return_value = True
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("DELETE", "/playlists/{id}/tracks/{track_id}",
                   path_params={"id": "p-1", "track_id": "t-1"}),
            None,
        )
    assert resp["statusCode"] == 204


def test_reorder_tracks_200() -> None:
    repo = MagicMock()
    repo.reorder_tracks.return_value = None
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/tracks/order",
                   body={"track_ids": ["t-2", "t-1"]},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_curation_handler_playlists.py -q`

- [ ] **Step 3: Add handlers + register**

In `src/collector/curation_handler.py`, add:

```python
def _playlist_track_response(row) -> dict[str, Any]:
    return {
        "track_id": row.track_id,
        "position": row.position,
        "added_at": row.added_at,
        "title": row.title,
        "spotify_id": row.spotify_id,
        "isrc": row.isrc,
        "length_ms": row.length_ms,
        "origin": row.origin,
    }


def _handle_list_playlist_tracks(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    rows, total = repo.list_tracks(
        user_id=user_id, playlist_id=pid, limit=limit, offset=offset,
    )
    return _json_response(
        200,
        {
            "items": [_playlist_track_response(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_add_playlist_tracks(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = AddTracksIn.model_validate(_parse_body(event))
    visible = repo.validate_tracks_in_scope(
        user_id=user_id, track_ids=body.track_ids,
    )
    missing = [t for t in body.track_ids if t not in visible]
    if missing:
        raise TrackNotInUserScopeError(
            "Some tracks are not accessible to the user", missing,
        )
    result = repo.append_tracks(
        user_id=user_id, playlist_id=pid,
        track_ids=body.track_ids, now=utc_now(),
    )
    log_event("INFO", "playlist_track_added",
              correlation_id=correlation_id, user_id=user_id,
              playlist_id=pid, n=len(result.added_track_ids))
    return _json_response(
        201,
        {
            "added": result.added_track_ids,
            "skipped_duplicates": result.skipped_duplicates,
            "position_after": result.position_after,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_remove_playlist_track(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    pid = pp.get("id")
    track_id = pp.get("track_id")
    if not pid or not track_id:
        raise ValidationError("id and track_id are required in path")
    ok = repo.remove_track(user_id=user_id, playlist_id=pid, track_id=track_id)
    if not ok:
        raise PlaylistNotFoundError("Playlist or track not found")
    log_event("INFO", "playlist_track_removed",
              correlation_id=correlation_id, user_id=user_id,
              playlist_id=pid, track_id=track_id)
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


def _handle_reorder_playlist_tracks(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = ReorderPlaylistTracksIn.model_validate(_parse_body(event))
    repo.reorder_tracks(
        user_id=user_id, playlist_id=pid,
        ordered_track_ids=body.track_ids, now=utc_now(),
    )
    log_event("INFO", "playlist_track_reordered",
              correlation_id=correlation_id, user_id=user_id,
              playlist_id=pid, size=len(body.track_ids))
    return _json_response(200, {"correlation_id": correlation_id}, correlation_id)
```

Append to `_ROUTE_TABLE`:

```python
    "GET /playlists/{id}/tracks": (_handle_list_playlist_tracks, _playlists_factory),
    "POST /playlists/{id}/tracks": (_handle_add_playlist_tracks, _playlists_factory),
    "DELETE /playlists/{id}/tracks/{track_id}": (
        _handle_remove_playlist_track, _playlists_factory,
    ),
    "POST /playlists/{id}/tracks/order": (
        _handle_reorder_playlist_tracks, _playlists_factory,
    ),
```

- [ ] **Step 4: Run, verify pass**

`pytest tests/unit/test_curation_handler_playlists.py -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_handler_playlists.py
git commit -m "$(cat <<'EOF'
feat(playlists): handler tracks routes

GET list, POST add, DELETE single, POST reorder. Add-path runs
scope-check first and surfaces missing track ids on 404 so the SPA
can highlight non-owned tracks.
EOF
)"
```

---

## Task 14: Handler — cover + import + publish routes (with service orchestration)

This task is the biggest. It introduces a small `playlists_publish_service.py` to keep `curation_handler.py` from ballooning, then wires routes.

**Files:**

- Create: `src/collector/curation/playlists_publish_service.py`
- Modify: `src/collector/curation_handler.py`
- Test: `tests/unit/test_playlists_publish_service.py`
- Modify: `tests/unit/test_curation_handler_playlists.py`

- [ ] **Step 1: Write failing publish-service tests**

Create `tests/unit/test_playlists_publish_service.py`:

```python
"""Publish/import service orchestration. Repository + Spotify client are
MagicMock — we assert on call order and effects."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call

import pytest

from collector.curation import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    SpotifyApiError,
)
from collector.curation.playlists_publish_service import (
    PublishResult,
    PlaylistsPublishService,
)


def _utc() -> datetime:
    return datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def _playlist(**overrides):
    base = dict(
        id="p-1", user_id="u-1", name="My Set", normalized_name="my set",
        description=None, is_public=False, cover_s3_key=None,
        cover_uploaded_at=None, spotify_playlist_id=None,
        last_published_at=None, needs_republish=False, track_count=2,
        created_at="2026-05-12T10:00:00+00:00",
        updated_at="2026-05-12T10:00:00+00:00",
    )
    base.update(overrides)
    return MagicMock(**base)


def _track(track_id, spotify_id):
    return MagicMock(
        track_id=track_id, position=0, added_at=_utc().isoformat(),
        title=track_id, spotify_id=spotify_id, isrc=None,
        length_ms=200000, origin="beatport",
    )


def _build(repo, sp_client, user_repo, s3, now=_utc):
    return PlaylistsPublishService(
        repo=repo, spotify_client=sp_client,
        user_repo=user_repo, storage=s3,
        now=now,
    )


def test_publish_first_time_creates_then_replaces_then_persists() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist()
    repo.list_tracks.return_value = ([_track("t-1", "spt-1"), _track("t-2", "spt-2")], 2)

    sp = MagicMock()
    sp.create_playlist.return_value = MagicMock(
        id="spt-pl-1", url="https://open.spotify.com/playlist/spt-pl-1",
    )

    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "user-spotify-id"

    s3 = MagicMock()

    svc = _build(repo, sp, user_repo, s3)
    result = svc.publish(
        user_id="u-1", playlist_id="p-1", confirm_overwrite=False,
    )
    assert isinstance(result, PublishResult)
    assert result.spotify_playlist_id == "spt-pl-1"
    assert result.skipped == []
    sp.create_playlist.assert_called_once()
    sp.replace_tracks.assert_called_once_with(
        "spt-pl-1", ["spotify:track:spt-1", "spotify:track:spt-2"],
    )
    repo.set_publish_state.assert_called_once()


def test_publish_skips_tracks_without_spotify_id() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist()
    repo.list_tracks.return_value = (
        [_track("t-1", "spt-1"), _track("t-2", None)], 2,
    )
    sp = MagicMock()
    sp.create_playlist.return_value = MagicMock(id="spt-pl-1", url=None)
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    s3 = MagicMock()

    svc = _build(repo, sp, user_repo, s3)
    result = svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)
    assert [s["track_id"] for s in result.skipped] == ["t-2"]
    sp.replace_tracks.assert_called_once_with(
        "spt-pl-1", ["spotify:track:spt-1"],
    )


def test_publish_empty_playlist_raises() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(track_count=0)
    repo.list_tracks.return_value = ([], 0)
    sp = MagicMock()
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    svc = _build(repo, sp, user_repo, MagicMock())
    with pytest.raises(NothingToPublishError):
        svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)


def test_repub_without_confirm_raises() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(spotify_playlist_id="existing")
    svc = _build(repo, MagicMock(), MagicMock(), MagicMock())
    with pytest.raises(ConfirmOverwriteRequiredError):
        svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)


def test_repub_with_confirm_uses_update_then_replace() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(spotify_playlist_id="existing")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    svc = _build(repo, sp, user_repo, MagicMock())
    svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=True)
    sp.update_playlist.assert_called_once()
    sp.replace_tracks.assert_called_once()


def test_repub_orphan_falls_back_to_create() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(spotify_playlist_id="orphan")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    sp.update_playlist.side_effect = SpotifyApiError("Spotify 404")
    sp.create_playlist.return_value = MagicMock(id="new-spt-id", url=None)
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    svc = _build(repo, sp, user_repo, MagicMock())
    result = svc.publish(
        user_id="u-1", playlist_id="p-1", confirm_overwrite=True,
        treat_404_as_orphan=True,
    )
    assert result.spotify_playlist_id == "new-spt-id"


def test_publish_uploads_cover_when_present() -> None:
    repo = MagicMock()
    repo.get.return_value = _playlist(cover_s3_key="covers/u/p/1.jpg")
    repo.list_tracks.return_value = ([_track("t-1", "spt-1")], 1)
    sp = MagicMock()
    sp.create_playlist.return_value = MagicMock(id="spt-1", url=None)
    user_repo = MagicMock()
    user_repo.get_spotify_id.return_value = "u-sp"
    s3 = MagicMock()
    s3.read_cover_bytes.return_value = b"\xff\xd8jpegbytes"
    svc = _build(repo, sp, user_repo, s3)
    svc.publish(user_id="u-1", playlist_id="p-1", confirm_overwrite=False)
    sp.set_cover.assert_called_once_with("spt-1", b"\xff\xd8jpegbytes")
```

- [ ] **Step 2: Run, verify fail**

`pytest tests/unit/test_playlists_publish_service.py -q`

- [ ] **Step 3: Implement publish service**

Create `src/collector/curation/playlists_publish_service.py`:

```python
"""Publish orchestration for playlists (spec 2026-05-11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from collector.logging_utils import log_event

from . import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    PlaylistNotFoundError,
    SpotifyApiError,
)


@dataclass(frozen=True)
class PublishResult:
    spotify_playlist_id: str
    spotify_url: str | None
    skipped: list[dict]
    published_at: str


class _UserRepoLike(Protocol):
    def get_spotify_id(self, user_id: str) -> str | None: ...


class PlaylistsPublishService:
    def __init__(
        self,
        *,
        repo,
        spotify_client,
        user_repo: _UserRepoLike,
        storage,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repo = repo
        self._sp = spotify_client
        self._user_repo = user_repo
        self._storage = storage
        self._now = now

    def publish(
        self,
        *,
        user_id: str,
        playlist_id: str,
        confirm_overwrite: bool,
        treat_404_as_orphan: bool = True,
    ) -> PublishResult:
        playlist = self._repo.get(user_id=user_id, playlist_id=playlist_id)
        if playlist is None:
            raise PlaylistNotFoundError()

        if playlist.spotify_playlist_id and not confirm_overwrite:
            raise ConfirmOverwriteRequiredError(
                "Playlist already published — pass confirm_overwrite=true to replace"
            )

        # Pull tracks; filter by spotify_id presence.
        rows, _total = self._repo.list_tracks(
            user_id=user_id, playlist_id=playlist_id,
            limit=10_000, offset=0,
        )
        skipped = [
            {"track_id": r.track_id, "title": r.title, "reason": "no_spotify_id"}
            for r in rows if not r.spotify_id
        ]
        uris = [f"spotify:track:{r.spotify_id}" for r in rows if r.spotify_id]
        if not uris:
            raise NothingToPublishError("Playlist has no playable tracks")

        user_spotify_id = self._user_repo.get_spotify_id(user_id)
        if not user_spotify_id:
            raise PlaylistNotFoundError("User has no linked Spotify identity")

        log_event(
            "INFO", "playlist_publish_started",
            user_id=user_id, playlist_id=playlist_id,
            first_time=not bool(playlist.spotify_playlist_id),
            track_count=len(uris),
            has_cover=bool(playlist.cover_s3_key),
        )

        target_id = playlist.spotify_playlist_id

        if target_id:
            try:
                self._sp.update_playlist(
                    spotify_playlist_id=target_id,
                    name=playlist.name,
                    description=playlist.description,
                    public=playlist.is_public,
                )
            except SpotifyApiError as exc:
                if treat_404_as_orphan and "404" in str(exc):
                    log_event("WARNING",
                              "playlist_publish_orphan_recreated",
                              user_id=user_id, playlist_id=playlist_id,
                              old_spotify_playlist_id=target_id)
                    target_id = None
                else:
                    raise
        if not target_id:
            ref = self._sp.create_playlist(
                user_spotify_id=user_spotify_id,
                name=playlist.name,
                description=playlist.description,
                public=playlist.is_public,
            )
            target_id = ref.id
            spotify_url = ref.url
        else:
            spotify_url = f"https://open.spotify.com/playlist/{target_id}"

        # Tracks: replace first 100, append rest.
        self._sp.replace_tracks(target_id, uris[:100])
        for i in range(100, len(uris), 100):
            self._sp.append_tracks(target_id, uris[i : i + 100])

        # Cover (best-effort): if read fails we log and skip rather than abort.
        if playlist.cover_s3_key:
            try:
                jpeg_bytes = self._storage.read_cover_bytes(playlist.cover_s3_key)
                self._sp.set_cover(target_id, jpeg_bytes)
            except Exception as exc:
                log_event(
                    "WARNING", "playlist_publish_partial_fail",
                    user_id=user_id, playlist_id=playlist_id,
                    stage="cover",
                    error_message=str(exc),
                    error_type=type(exc).__name__,
                )

        now = self._now()
        self._repo.set_publish_state(
            user_id=user_id, playlist_id=playlist_id,
            spotify_playlist_id=target_id, now=now,
        )
        log_event(
            "INFO", "playlist_publish_succeeded",
            user_id=user_id, playlist_id=playlist_id,
            spotify_playlist_id=target_id, skipped=len(skipped),
        )
        return PublishResult(
            spotify_playlist_id=target_id,
            spotify_url=spotify_url,
            skipped=skipped,
            published_at=now.isoformat(),
        )
```

- [ ] **Step 4: Run publish-service tests, verify pass**

`pytest tests/unit/test_playlists_publish_service.py -q` → all PASS.

- [ ] **Step 5: Add cover + import + publish handler routes**

In `curation_handler.py` add handlers (cover-upload-url, cover-confirm, cover-delete, import-spotify, publish). They need an additional factory that produces the spotify user client; see implementation hint:

```python
def _build_spotify_user_client(user_id: str, correlation_id: str):
    """Build SpotifyUserClient with refreshed access token for user_id.

    Lazy import to keep cold-start light. Token resolver + envelope come
    from collector.auth.kms_envelope and collector.auth.spotify_oauth.
    """
    import requests as _requests
    from collector.auth.auth_settings import (
        get_auth_settings, resolve_oauth_client_credentials,
    )
    from collector.auth.kms_envelope import KmsEnvelope
    from collector.auth.spotify_oauth import SpotifyOAuthClient
    from collector.data_api import create_default_data_api_client
    from collector.curation.spotify_token_resolver import SpotifyTokenResolver
    from collector.curation.spotify_user_client import SpotifyUserClient
    from collector.settings import get_data_api_settings
    import boto3

    db = get_data_api_settings()
    auth = get_auth_settings()
    cid, csec = resolve_oauth_client_credentials()
    data_api = create_default_data_api_client(
        resource_arn=str(db.aurora_cluster_arn),
        secret_arn=str(db.aurora_secret_arn),
        database=db.aurora_database,
    )
    envelope = KmsEnvelope(
        kms_client=boto3.client("kms"),
        key_arn=auth.kms_user_tokens_key_arn,
    )
    oauth = SpotifyOAuthClient(
        client_id=cid, client_secret=csec,
        redirect_uri=auth.spotify_oauth_redirect_uri,
    )
    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    token = resolver.resolve(user_id=user_id)
    return SpotifyUserClient(
        access_token=token.access_token,
        session=_requests.Session(),
    )
```

Add the cover/import/publish handlers; they all use `_playlists_factory()` as the repository factory and call `_build_spotify_user_client` lazily inside the handler where Spotify is needed.

> **Implementation hints rather than spelled-out code, because handler glue is repetitive and the patterns are now established. Each handler:**
>
> - `POST /playlists/{id}/cover/upload-url`: parse `CoverUploadUrlIn`, check `repo.get()` exists, build `S3Storage`, compute `epoch_ms = int(now.timestamp()*1000)`, build key via `S3Storage.cover_key`, return `{upload_url, s3_key, expires_in: 300}`.
> - `POST /playlists/{id}/cover/confirm`: read body → resolve `s3_key` (server cached the last issued one? — simpler: trust the client to pass `s3_key`; or `repo` remembers the candidate; **decision: include `s3_key` in the confirm body** for stateless backend). HEAD the object via `storage.head_cover`; on `None` raise `CoverMissingError`; on size > 262_144 raise `CoverTooLargeError`. Then `repo.set_cover`.
> - `DELETE /playlists/{id}/cover`: `repo.clear_cover`; 404 if returns False.
> - `POST /playlists/{id}/tracks/import-spotify`: parse `ImportSpotifyTracksIn`. For each ref: try `parse_spotify_ref` — catch `InvalidSpotifyRefError` → push to `skipped` with `invalid_ref`. Build `SpotifyUserClient` once. For each parsed spotify_id: `sp.get_track`; on 404 push to `skipped` with `not_found`. Call `repo.upsert_imported_track`. Then `repo.append_tracks` with the resolved canonical track_ids. Return same shape as add-tracks but with `added: [{track_id, spotify_id, title}]`.
> - `POST /playlists/{id}/publish`: parse `PublishPlaylistIn`. Build sp client + a thin user repo (see Task 14 step 6). Construct `PlaylistsPublishService` and call `.publish`.

**Add a thin `UserSpotifyIdReader` next to the publish service:**

In `playlists_publish_service.py`:

```python
class UserSpotifyIdReader:
    def __init__(self, data_api) -> None:
        self._data_api = data_api

    def get_spotify_id(self, user_id: str) -> str | None:
        rows = self._data_api.execute(
            "SELECT spotify_id FROM users WHERE id = :id",
            {"id": user_id},
        )
        return rows[0]["spotify_id"] if rows else None
```

Build it inside the handler from the existing `data_api` settings.

**Register new routes** in `_ROUTE_TABLE`:

```python
    "POST /playlists/{id}/cover/upload-url": (
        _handle_cover_upload_url, _playlists_factory,
    ),
    "POST /playlists/{id}/cover/confirm": (
        _handle_cover_confirm, _playlists_factory,
    ),
    "DELETE /playlists/{id}/cover": (
        _handle_cover_delete, _playlists_factory,
    ),
    "POST /playlists/{id}/tracks/import-spotify": (
        _handle_import_spotify, _playlists_factory,
    ),
    "POST /playlists/{id}/publish": (
        _handle_publish, _playlists_factory,
    ),
```

- [ ] **Step 6: Add handler-level smoke tests**

Append to `tests/unit/test_curation_handler_playlists.py`:

```python
def test_cover_upload_url_returns_presign_metadata() -> None:
    repo = MagicMock()
    repo.get.return_value = MagicMock(id="p-1")  # exists
    with _patch_factory(repo), patch(
        "collector.curation_handler._build_s3_storage"
    ) as s3_factory:
        s3 = MagicMock()
        s3.cover_key.return_value = "covers/u-1/p-1/123.jpg"
        s3.presigned_cover_put_url.return_value = "https://signed"
        s3_factory.return_value = s3
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/cover/upload-url",
                   body={"content_type": "image/jpeg"},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://signed"
    assert body["s3_key"].startswith("covers/u-1/p-1/")


def test_cover_confirm_404_when_missing() -> None:
    repo = MagicMock()
    repo.get.return_value = MagicMock(id="p-1")
    with _patch_factory(repo), patch(
        "collector.curation_handler._build_s3_storage"
    ) as s3_factory:
        s3 = MagicMock()
        s3.head_cover.return_value = None
        s3_factory.return_value = s3
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/cover/confirm",
                   body={"s3_key": "covers/u-1/p-1/123.jpg"},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "cover_missing"


def test_publish_returns_412_when_no_spotify_token() -> None:
    repo = MagicMock()
    repo.get.return_value = MagicMock(spotify_playlist_id=None)
    with _patch_factory(repo), patch(
        "collector.curation_handler._build_spotify_user_client",
        side_effect=__import__(
            "collector.curation", fromlist=["SpotifyNotAuthorizedError"]
        ).SpotifyNotAuthorizedError("no token"),
    ):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/publish",
                   body={"confirm_overwrite": False},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 412
```

Add a small `_build_s3_storage` helper in the handler module (mirrors auth_handler's lazy boto builders):

```python
def _build_s3_storage():
    import boto3
    from collector.storage import S3Storage
    from collector.settings import get_settings  # or wherever raw_bucket_name lives
    s = get_settings()
    return S3Storage(
        s3_client=boto3.client("s3"),
        bucket_name=s.raw_bucket_name,
        raw_prefix="raw/bp/releases",  # unused for covers; key is absolute
    )
```

> **If `get_settings().raw_bucket_name` isn't the right accessor in this codebase, find the existing pattern in `handler.py` for how the API Lambda reads `RAW_BUCKET_NAME` and reuse that.**

- [ ] **Step 7: Run all unit tests, verify pass**

```bash
pytest tests/unit/test_curation_handler_playlists.py \
       tests/unit/test_playlists_publish_service.py -q
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/collector/curation/playlists_publish_service.py \
        src/collector/curation_handler.py \
        tests/unit/test_playlists_publish_service.py \
        tests/unit/test_curation_handler_playlists.py
git commit -m "$(cat <<'EOF'
feat(playlists): cover + import + publish handlers

Publish service handles first-time create, re-publish with
confirm_overwrite, orphan-fallback (404 on update → create), track
batching, cover upload, and persisted publish state. Cover handlers
use presigned PUT + HEAD validation. Import handler resolves
Spotify refs, fetches via SpotifyUserClient, upserts canonical
clouder_tracks, marks user_imported_tracks.
EOF
)"
```

---

## Task 15: OpenAPI ROUTES + Terraform routes file + IAM

**Files:**

- Modify: `scripts/generate_openapi.py`
- Create: `infra/curation_routes_playlists.tf`
- Modify: `infra/curation.tf` (IAM additions)

- [ ] **Step 1: Append OpenAPI ROUTES**

In `scripts/generate_openapi.py`, append twelve entries to the `ROUTES` list following the existing categories/tags pattern. Each route uses `auth=AUTHENTICATED`, references the playlist schemas (define them as additional component schemas next to the existing category ones), and lists the 4xx error envelopes. The 12 routes (verbatim):

```
POST /playlists
GET /playlists
GET /playlists/{id}
PATCH /playlists/{id}
DELETE /playlists/{id}
GET /playlists/{id}/tracks
POST /playlists/{id}/tracks
DELETE /playlists/{id}/tracks/{track_id}
POST /playlists/{id}/tracks/order
POST /playlists/{id}/cover/upload-url
POST /playlists/{id}/cover/confirm
DELETE /playlists/{id}/cover
POST /playlists/{id}/tracks/import-spotify
POST /playlists/{id}/publish
```

(That is 14 — adjust the headline number anywhere it says "12 routes" in the spec; this is a counting fix.)

Regenerate: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py` (writes `docs/openapi.yaml`). Verify no errors.

- [ ] **Step 2: Create Terraform routes file**

Create `infra/curation_routes_playlists.tf`:

```hcl
# ── curation Lambda playlist routes (spec 2026-05-11) ────────────────
# Append-only: reuses the curation Lambda integration + JWT authorizer
# defined in curation.tf.

locals {
  curation_playlist_routes = [
    "POST /playlists",
    "GET /playlists",
    "GET /playlists/{id}",
    "PATCH /playlists/{id}",
    "DELETE /playlists/{id}",
    "GET /playlists/{id}/tracks",
    "POST /playlists/{id}/tracks",
    "DELETE /playlists/{id}/tracks/{track_id}",
    "POST /playlists/{id}/tracks/order",
    "POST /playlists/{id}/cover/upload-url",
    "POST /playlists/{id}/cover/confirm",
    "DELETE /playlists/{id}/cover",
    "POST /playlists/{id}/tracks/import-spotify",
    "POST /playlists/{id}/publish",
  ]
}

resource "aws_apigatewayv2_route" "curation_playlists" {
  for_each = toset(local.curation_playlist_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.curation.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 3: Extend IAM (S3 covers + KMS)**

Find the existing IAM policy attached to `aws_iam_role.collector_lambda` (usually in `infra/iam.tf`). Add a new policy or extend the existing one with:

```hcl
data "aws_iam_policy_document" "curation_covers" {
  statement {
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:HeadObject",
    ]
    resources = ["${aws_s3_bucket.raw.arn}/covers/*"]
  }

  statement {
    actions = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.user_tokens.arn]
  }
}

resource "aws_iam_policy" "curation_covers" {
  name   = "${local.name_prefix}-curation-covers"
  policy = data.aws_iam_policy_document.curation_covers.json
}

resource "aws_iam_role_policy_attachment" "curation_covers" {
  role       = aws_iam_role.collector_lambda.name
  policy_arn = aws_iam_policy.curation_covers.arn
}
```

> **Verify** that `aws_kms_key.user_tokens` exists in your auth Terraform (it should — auth_handler uses it). If named differently, adjust.

- [ ] **Step 4: terraform fmt + plan**

```bash
cd infra
terraform fmt
terraform validate
terraform plan -var-file=prod.tfvars  # whatever your dev plan invocation is
```

Expected: clean fmt, `+ 14 route resources`, `+ aws_iam_policy.curation_covers`, `+ attachment`.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_openapi.py docs/openapi.yaml \
        infra/curation_routes_playlists.tf infra/iam.tf
git commit -m "$(cat <<'EOF'
feat(playlists): openapi + terraform routes + IAM

14 API GW routes via curation_routes_playlists.tf. IAM grants S3
covers/* + KMS Decrypt/Encrypt/GenerateDataKey on the user-tokens
key (required for SpotifyTokenResolver inside curation Lambda).
EOF
)"
```

---

## Task 16: Integration test — end-to-end flow

**Files:**

- Create: `tests/integration/test_playlists_flow.py`

Uses ephemeral Postgres + boto3 mocks (existing pattern from `test_curation_handler.py`). Walks the user through CRUD + cover + import + publish, asserting against the database state and recorded mock calls.

- [ ] **Step 1: Write the integration test scaffold**

Create `tests/integration/test_playlists_flow.py`:

```python
"""End-to-end Playlists flow against ephemeral Postgres.

Mirrors the shape of tests/integration/test_curation_handler.py:
fixtures spin up a temp pg, run alembic upgrade head, seed a user
with a Spotify token row, then exercise the handler.

Spotify HTTP + S3 are stubbed via MagicMock — same access points as
the unit tests."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Bring in shared fixtures from the integration package.
pytestmark = pytest.mark.usefixtures("aurora_pg")


def _event(method: str, path: str, user_id: str,
           body: dict | None = None,
           path_params: dict | None = None) -> dict:
    return {
        "requestContext": {
            "routeKey": f"{method} {path}",
            "authorizer": {"lambda": {"user_id": user_id}},
        },
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else "",
        "headers": {"x-correlation-id": "cid-int"},
    }


def test_full_lifecycle(aurora_pg, seeded_user, fake_clouder_track):
    from collector.curation_handler import lambda_handler

    user_id = seeded_user
    track_id = fake_clouder_track  # canonical track with spotify_id, in a user category

    # 1. Create
    resp = lambda_handler(
        _event("POST", "/playlists", user_id, {"name": "My Set"}),
        None,
    )
    assert resp["statusCode"] == 201
    pid = json.loads(resp["body"])["id"]

    # 2. List
    resp = lambda_handler(_event("GET", "/playlists", user_id), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["total"] == 1

    # 3. Add a track from user's category
    resp = lambda_handler(
        _event(
            "POST", "/playlists/{id}/tracks", user_id,
            body={"track_ids": [track_id]},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 201

    # 4. Try to add a foreign track → 404
    foreign_track_id = str(uuid.uuid4())
    aurora_pg.execute(
        """
        INSERT INTO clouder_tracks (id, title, origin)
        VALUES (%s, 'foreign', 'beatport')
        """,
        (foreign_track_id,),
    )
    resp = lambda_handler(
        _event(
            "POST", "/playlists/{id}/tracks", user_id,
            body={"track_ids": [foreign_track_id]},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert foreign_track_id in body["missing_track_ids"]

    # 5. Soft-delete
    resp = lambda_handler(
        _event("DELETE", "/playlists/{id}", user_id, path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 204
    resp = lambda_handler(_event("GET", "/playlists", user_id), None)
    assert json.loads(resp["body"])["total"] == 0


def test_publish_first_time_full_flow(aurora_pg, seeded_user, fake_clouder_track):
    from collector.curation_handler import lambda_handler

    user_id = seeded_user
    track_id = fake_clouder_track

    # Seed playlist with one track.
    resp = lambda_handler(
        _event("POST", "/playlists", user_id, {"name": "Set"}),
        None,
    )
    pid = json.loads(resp["body"])["id"]
    lambda_handler(
        _event(
            "POST", "/playlists/{id}/tracks", user_id,
            body={"track_ids": [track_id]},
            path_params={"id": pid},
        ),
        None,
    )

    sp_client = MagicMock()
    sp_client.create_playlist.return_value = MagicMock(
        id="spt-1", url="https://open.spotify.com/playlist/spt-1",
    )

    with patch(
        "collector.curation_handler._build_spotify_user_client",
        return_value=sp_client,
    ):
        resp = lambda_handler(
            _event(
                "POST", "/playlists/{id}/publish", user_id,
                body={"confirm_overwrite": False},
                path_params={"id": pid},
            ),
            None,
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["spotify_playlist_id"] == "spt-1"
    sp_client.create_playlist.assert_called_once()
    sp_client.replace_tracks.assert_called_once()

    # DB should now show spotify_playlist_id + needs_republish=false.
    rows = aurora_pg.fetch_one(
        "SELECT spotify_playlist_id, needs_republish FROM playlists WHERE id = %s",
        (pid,),
    )
    assert rows["spotify_playlist_id"] == "spt-1"
    assert rows["needs_republish"] is False


def test_repub_without_confirm_returns_409(aurora_pg, seeded_user):
    # Set up: a playlist with spotify_playlist_id set.
    from collector.curation_handler import lambda_handler

    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    aurora_pg.execute(
        """
        INSERT INTO playlists (
            id, user_id, name, normalized_name, is_public,
            spotify_playlist_id, needs_republish, created_at, updated_at
        ) VALUES (%s, %s, 'p', 'p', false, 'spt-existing', true, %s, %s)
        """,
        (pid, seeded_user, now, now),
    )
    sp_client = MagicMock()
    with patch(
        "collector.curation_handler._build_spotify_user_client",
        return_value=sp_client,
    ):
        resp = lambda_handler(
            _event(
                "POST", "/playlists/{id}/publish", seeded_user,
                body={"confirm_overwrite": False},
                path_params={"id": pid},
            ),
            None,
        )
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["error_code"] == "confirm_overwrite_required"
```

> **Fixtures `aurora_pg`, `seeded_user`, `fake_clouder_track` either exist already in `tests/integration/conftest.py` (check first) or you must add them following the existing patterns. The conftest already supports `aurora_pg`; new fixtures should live in the integration conftest and emit the minimum rows required (a user with `spotify_id`, a `user_vendor_tokens.spotify` row pre-encrypted, a clouder_style, a category, a clouder_track in that category with `spotify_id`).

- [ ] **Step 2: Run, verify (likely needs fixtures + small handler fixes)**

```bash
pytest tests/integration/test_playlists_flow.py -q
```

If fixtures are missing, add minimal versions in `tests/integration/conftest.py`. Iterate until green. Don't add new application code unless tests reveal a real handler bug.

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
pytest -q
```

Expected: 100% pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_playlists_flow.py tests/integration/conftest.py
git commit -m "$(cat <<'EOF'
test(playlists): end-to-end integration flow

CRUD lifecycle, foreign-track rejection, full publish-first-time
with stubbed SpotifyUserClient, re-publish without confirm → 409.
Uses ephemeral postgres + alembic upgrade head from existing
integration fixtures.
EOF
)"
```

---

## Self-Review Notes (post-write check)

Run these checks before handing off:

1. **Spec coverage:**
   - Data model (migration + models) → Task 1.
   - Errors → Task 2.
   - Service helpers (validate/normalize/parse/reorder) → Task 3.
   - Repository CRUD → Task 4.
   - Tracks (append / remove / reorder / list) → Task 5.
   - Cover + publish state → Task 6.
   - Scope check + import upsert → Task 7.
   - Token resolver → Task 8.
   - Spotify HTTP client → Task 9.
   - Storage cover helpers → Task 10.
   - Pydantic schemas → Task 11.
   - Handler CRUD → Task 12.
   - Handler tracks → Task 13.
   - Cover + import + publish handlers + service → Task 14.
   - OpenAPI + Terraform + IAM → Task 15.
   - Integration → Task 16.

2. **Placeholder scan:** Every step has a code block or an exact command. Where a code block is replaced by hints (Task 14 cover/import/publish handler glue) the patterns are fully established in earlier tasks — keep an eye out for any handler signature drift between Task 12 ↔ Task 14.

3. **Type consistency:**
   - `PlaylistRow.created_at` is `str` (consistent with CategoryRow ISO string convention).
   - `PlaylistsRepository` methods are all `*, kw-only` — consistent.
   - Service constants live in `playlists_service.py`; handler imports them.
   - Publish service `now: Callable[[], datetime]` matches how categories repository receives `now` from the handler (no callable, just a datetime). The publish service uses a callable so tests can pin time; handler passes `lambda: utc_now()`.

4. **Known fragile bits the implementer should watch for:**
   - `upsert_imported_track` SQL must list every NOT NULL column on `clouder_tracks`. Inspect `db_models.py` before running.
   - `_build_s3_storage` accessor for `RAW_BUCKET_NAME` — use whatever the API Lambda uses; do not invent a new settings shape.
   - Auth `KmsEnvelope` is already in `collector.auth.kms_envelope` — no need to extract a new module (spec drift; design doc mentions `secrets_envelope.py`).
   - `DEFERRABLE INITIALLY DEFERRED` unique requires raw SQL in Alembic.
   - When asserting on `aurora_pg` boolean columns, Postgres returns Python booleans only if your DB driver returns them — most psycopg drivers do. If the existing test pattern uses different assertions, follow that pattern.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-11-playlists-backend.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between, fast iteration.

**2. Inline Execution** — execute tasks in this session via `superpowers:executing-plans`, batch checkpoints.

**Which approach?**

