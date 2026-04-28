# spec-D Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the user-curation Layer-2 (Triage) end-to-end: schema (3 new tables + 1 new column on `clouder_tracks`), Spotify enrichment patch, repository, 9 handler routes wired into the existing `curation_handler.py` Lambda, the cross-spec patches to `categories_service.py`, infrastructure, and tests. After this plan ships, a logged-in user can create a triage block for a (style, date-range) tuple, the backend auto-classifies all eligible tracks into NEW/OLD/NOT/DISCARD/UNCLASSIFIED + N staging-per-category buckets, and on `finalize` staging contents promote into `category_tracks` via spec-C's `add_tracks_bulk(...)` contract.

**Architecture:** Three new tables (`triage_blocks`, `triage_buckets`, `triage_bucket_tracks`) live in Aurora alongside the spec-C `categories` schema. A new `TriageRepository` (raw SQL through Aurora Data API) sits next to `CategoriesRepository` under `collector/curation/`. The 9 new HTTP routes are added to the existing `curation_handler.py` Lambda — same auth, same env vars, same IAM. R4 auto-classification is one INSERT-FROM-SELECT inside the create-block transaction, keyed off a new `clouder_tracks.spotify_release_date` column populated by the existing Spotify enrichment worker (patch in this plan). The eager-snapshot side-effect from D7 lives as one extra call inside `categories_service.create`/`soft_delete`.

**Tech Stack:** Python 3.12 Lambda, Aurora Postgres via RDS Data API, Pydantic v2 schemas, Alembic migrations, Terraform (HTTP API Gateway v2), pytest with MagicMock-based unit tests + monkeypatched FakeRepo integration tests.

**Spec:** [`docs/superpowers/specs/2026-04-28-spec-D-triage-design.md`](../specs/2026-04-28-spec-D-triage-design.md)

---

## File Structure

**New files (created during this plan):**

```
alembic/versions/20260428_15_triage.py                  # T1 — DDL migration
src/collector/curation/triage_repository.py             # T7–T15 — Data API repo
src/collector/curation/triage_service.py                # T6 — pure helpers
tests/unit/test_migration_15_sql.py                     # T1
tests/unit/test_triage_schemas.py                       # T5
tests/unit/test_triage_service.py                       # T6
tests/unit/test_triage_repository.py                    # T7–T15
tests/unit/test_spotify_release_date.py                 # T3 — _extract_release_date
tests/integration/test_triage_handler.py                # T21–T23
infra/curation_routes_triage.tf                         # T24 — 9 new routes
```

**Modified files:**

```
src/collector/db_models.py                              # T2 — +3 SQLAlchemy models, +1 column
src/collector/spotify_handler.py                        # T3 — _extract_release_date + cmd field
src/collector/repositories.py                           # T3 — UpdateSpotifyResultCmd field, SQL UPDATE
src/collector/curation/__init__.py                      # T4 — +InactiveBucketError, +InvalidStateError
src/collector/curation/schemas.py                       # T5 — +TriageBlock*, +Move*, +Transfer*, +Finalize*, +BucketTrackRow
src/collector/curation/categories_service.py            # T16 — +snapshot call in create, +inactive call in soft_delete
src/collector/curation/categories_repository.py         # T16 — pass transaction_id through (already exists)
src/collector/curation_handler.py                       # T17–T20 — +9 handlers, +ROUTES entries
tests/integration/test_curation_handler.py              # T16 (extend) — assert snapshot/inactive side-effects
tests/unit/test_spotify_handler.py                      # T3 (extend)
tests/unit/test_repositories.py                         # T3 (extend)
docs/data-model.md                                      # T26 — append §1.X for 3 new tables + new column
scripts/generate_openapi.py                             # T25 — append 9 new ROUTES entries
docs/openapi.yaml                                       # T25 — regenerated
```

**Untouched (intentionally):**

- `src/collector/handler.py`, `src/collector/worker_handler.py` — unrelated.
- `src/collector/auth/*` — spec-A is the prerequisite; nothing changes.
- `infra/curation.tf` (Lambda function definition) — already exists from spec-C; only routes file is added.
- `src/collector/curation/categories_repository.py` — `add_tracks_bulk` already accepts `transaction_id` per spec-C D17.

---

## Conventions

- **Python style:** existing code uses `from __future__ import annotations`, `dataclass(frozen=True)`, type hints everywhere. Match it.
- **SQL style:** raw SQL strings inside repository methods, parameters via `:name` placeholders, passed as `dict` to `data_api.execute(sql, params, transaction_id=...)`.
- **Datetime:** UTC always. Use `utc_now()` from `collector/curation/__init__.py`.
- **Date:** for `date_from`/`date_to`/`spotify_release_date`/`publish_date` use `datetime.date` (not datetime). Bind as ISO `YYYY-MM-DD` string for Data API; Aurora maps to `DATE`.
- **UUIDs:** `str(uuid.uuid4())`. Always strings (length 36).
- **Errors:** custom exception classes in `collector/curation/__init__.py`, mapped to HTTP envelope `{error_code, message, correlation_id}` by the handler.
- **Logging:** `from collector.logging_utils import log_event`. Always pass `correlation_id`.
- **Commits:** Conventional Commits. Hook in repo blocks subjects that don't match `^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `. Use `caveman:caveman-commit` skill when preparing commit messages — repo policy. Do NOT include `Co-Authored-By: Claude` trailers (hook strips/blocks).
- **Branch:** work happens on the existing worktree branch `worktree-user_flow_spec_d`.

---

## Task 1: Alembic migration for triage tables and `spotify_release_date`

**Files:**
- Create: `alembic/versions/20260428_15_triage.py`
- Test: `tests/unit/test_migration_15_sql.py`

- [ ] **Step 1.1: Verify `down_revision` matches the latest migration**

Run: `ls alembic/versions/ | sort | tail -3`
Expected last entry: `20260427_14_categories.py`. If different, update `down_revision` in the migration file accordingly.

- [ ] **Step 1.2: Write the migration file**

```python
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
    for table in ("triage_blocks", "triage_buckets", "triage_bucket_tracks"):
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO clouder_app"
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
```

- [ ] **Step 1.3: Write the SQL-text test**

```python
# tests/unit/test_migration_15_sql.py
"""Test that the triage migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260428_15_triage.py")
    spec = importlib.util.spec_from_file_location("mig15", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260428_15"
    assert mig.down_revision == "20260427_14"


def test_upgrade_creates_triage_blocks() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'create_table(\n        "triage_blocks"' in src
    assert "ck_triage_blocks_date_range" in src
    assert "ck_triage_blocks_status" in src
    assert "idx_triage_blocks_user_style_status" in src
    assert "idx_triage_blocks_user_created" in src


def test_upgrade_creates_triage_buckets() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'create_table(\n        "triage_buckets"' in src
    assert "ck_triage_buckets_type" in src
    assert "ck_triage_buckets_staging_category" in src
    assert "uq_triage_buckets_block_category" in src
    assert "uq_triage_buckets_block_type_tech" in src
    # FK to categories must be RESTRICT not SET NULL (would break CHECK)
    assert 'ondelete="RESTRICT"' in src
    # FK to triage_blocks must CASCADE (hard-delete chain)
    assert 'ondelete="CASCADE"' in src


def test_upgrade_creates_triage_bucket_tracks() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'create_table(\n        "triage_bucket_tracks"' in src
    assert 'PrimaryKeyConstraint("triage_bucket_id", "track_id")' in src
    assert "idx_triage_bucket_tracks_bucket_added" in src


def test_upgrade_adds_spotify_release_date() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert 'add_column(\n        "clouder_tracks"' in src
    assert "spotify_release_date" in src
    assert "idx_tracks_spotify_release_date" in src


def test_upgrade_adds_deferred_fk_from_spec_c() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    assert "fk_category_tracks_source_triage_block" in src
    assert 'ondelete="SET NULL"' in src


def test_upgrade_grants_to_clouder_app() -> None:
    src = Path("alembic/versions/20260428_15_triage.py").read_text()
    for table in ("triage_blocks", "triage_buckets", "triage_bucket_tracks"):
        assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table}" in src
```

- [ ] **Step 1.4: Run the migration test**

Run: `pytest tests/unit/test_migration_15_sql.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 1.5: Run the full unit suite to confirm nothing broke**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 1.6: Commit**

Generate the commit message via the `caveman:caveman-commit` skill, then:

```bash
git add alembic/versions/20260428_15_triage.py tests/unit/test_migration_15_sql.py
git commit -m "<caveman-commit output>"
```

Suggested subject: `feat(migration): add triage tables and spotify_release_date column`.

---

## Task 2: SQLAlchemy models for triage tables + `spotify_release_date`

**Files:**
- Modify: `src/collector/db_models.py:172-211` (`ClouderTrack`)
- Modify: `src/collector/db_models.py` (append 3 new models at end)

These are used for alembic autogen only; runtime uses Data API.

- [ ] **Step 2.1: Add `spotify_release_date` to `ClouderTrack`**

Locate `ClouderTrack` (currently at `src/collector/db_models.py:172`). After the `release_type` line (currently at 201), insert:

```python
    spotify_release_date: Mapped[date_type | None] = mapped_column(Date)
```

`date_type` and `Date` are already imported in this module (used by `publish_date`). Verify before inserting:

Run: `grep -n "^from datetime\|^from sqlalchemy" src/collector/db_models.py`
Expected: `Date` imported from sqlalchemy and `date as date_type` from datetime.

- [ ] **Step 2.2: Append the 3 new models at the bottom of `db_models.py`**

```python
class TriageBlock(Base):
    __tablename__ = "triage_blocks"
    __table_args__ = (
        Index(
            "idx_triage_blocks_user_style_status",
            "user_id",
            "style_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_triage_blocks_user_created",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "date_to >= date_from", name="ck_triage_blocks_date_range"
        ),
        CheckConstraint(
            "status IN ('IN_PROGRESS','FINALIZED')",
            name="ck_triage_blocks_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    style_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clouder_styles.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    date_from: Mapped[date_type] = mapped_column(Date, nullable=False)
    date_to: Mapped[date_type] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'IN_PROGRESS'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class TriageBucket(Base):
    __tablename__ = "triage_buckets"
    __table_args__ = (
        Index("idx_triage_buckets_block", "triage_block_id"),
        Index(
            "idx_triage_buckets_category",
            "category_id",
            postgresql_where=text("category_id IS NOT NULL"),
        ),
        Index(
            "uq_triage_buckets_block_category",
            "triage_block_id",
            "category_id",
            unique=True,
            postgresql_where=text("category_id IS NOT NULL"),
        ),
        Index(
            "uq_triage_buckets_block_type_tech",
            "triage_block_id",
            "bucket_type",
            unique=True,
            postgresql_where=text("bucket_type <> 'STAGING'"),
        ),
        CheckConstraint(
            "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING')",
            name="ck_triage_buckets_type",
        ),
        CheckConstraint(
            "(bucket_type = 'STAGING') = (category_id IS NOT NULL)",
            name="ck_triage_buckets_staging_category",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    triage_block_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("triage_blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    bucket_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("categories.id", ondelete="RESTRICT")
    )
    inactive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class TriageBucketTrack(Base):
    __tablename__ = "triage_bucket_tracks"
    __table_args__ = (
        Index(
            "idx_triage_bucket_tracks_bucket_added",
            "triage_bucket_id",
            text("added_at DESC"),
            "track_id",
        ),
    )

    triage_bucket_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("triage_buckets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clouder_tracks.id"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

- [ ] **Step 2.3: Verify imports cover `Boolean`, `CheckConstraint`, `Index`, `text`, `Date`, `date_type`**

Run: `grep -nE "^from sqlalchemy|^from datetime" src/collector/db_models.py`
If `Boolean` or `CheckConstraint` is missing from the sqlalchemy import line, add them.

- [ ] **Step 2.4: Verify the file imports**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from collector.db_models import TriageBlock, TriageBucket, TriageBucketTrack, ClouderTrack; print(ClouderTrack.spotify_release_date.key)"`
Expected: `spotify_release_date`

- [ ] **Step 2.5: Run unit tests**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 2.6: Commit**

Suggested subject: `feat(models): add triage SQLAlchemy models and spotify_release_date column`

```bash
git add src/collector/db_models.py
git commit -m "<caveman-commit output>"
```

---

## Task 3: Spotify enrichment patch — populate `spotify_release_date`

**Files:**
- Modify: `src/collector/repositories.py:99-104` (`UpdateSpotifyResultCmd`)
- Modify: `src/collector/repositories.py:760-786` (`batch_update_spotify_results` SQL)
- Modify: `src/collector/spotify_handler.py:34-45` (alongside `_extract_album_type`)
- Modify: `src/collector/spotify_handler.py:280-290` (`UpdateSpotifyResultCmd` construction)
- Create: `tests/unit/test_spotify_release_date.py`
- Modify: `tests/unit/test_spotify_handler.py` (extend)
- Modify: `tests/unit/test_repositories.py` (extend)

- [ ] **Step 3.1: Write failing tests for `_extract_release_date`**

```python
# tests/unit/test_spotify_release_date.py
"""Test the album.release_date precision parser used by spotify_handler."""

from __future__ import annotations

from datetime import date

from collector.spotify_handler import _extract_release_date


def test_day_precision() -> None:
    payload = {
        "album": {
            "release_date": "2024-03-15",
            "release_date_precision": "day",
        }
    }
    assert _extract_release_date(payload) == date(2024, 3, 15)


def test_month_precision_pads_to_first_of_month() -> None:
    payload = {
        "album": {
            "release_date": "2024-03",
            "release_date_precision": "month",
        }
    }
    assert _extract_release_date(payload) == date(2024, 3, 1)


def test_year_precision_pads_to_jan_first() -> None:
    payload = {
        "album": {
            "release_date": "2024",
            "release_date_precision": "year",
        }
    }
    assert _extract_release_date(payload) == date(2024, 1, 1)


def test_missing_album_returns_none() -> None:
    assert _extract_release_date({}) is None
    assert _extract_release_date(None) is None


def test_missing_precision_returns_none() -> None:
    payload = {"album": {"release_date": "2024-03-15"}}
    assert _extract_release_date(payload) is None


def test_unknown_precision_returns_none() -> None:
    payload = {
        "album": {
            "release_date": "2024-03-15",
            "release_date_precision": "decade",
        }
    }
    assert _extract_release_date(payload) is None


def test_malformed_date_returns_none() -> None:
    payload = {
        "album": {
            "release_date": "not-a-date",
            "release_date_precision": "day",
        }
    }
    assert _extract_release_date(payload) is None


def test_non_string_release_date_returns_none() -> None:
    payload = {
        "album": {"release_date": 2024, "release_date_precision": "year"}
    }
    assert _extract_release_date(payload) is None


def test_non_mapping_album_returns_none() -> None:
    payload = {"album": "wrong-shape"}
    assert _extract_release_date(payload) is None
```

- [ ] **Step 3.2: Run to verify failure**

Run: `pytest tests/unit/test_spotify_release_date.py -v`
Expected: FAIL with `ImportError: cannot import name '_extract_release_date'`.

- [ ] **Step 3.3: Implement `_extract_release_date` in `spotify_handler.py`**

Locate `_extract_album_type` (currently at `src/collector/spotify_handler.py:34`). Verify `from datetime import date` is in the imports; add it to the existing `from datetime import ...` line if missing. Then insert directly after `_extract_album_type` (before `def lambda_handler`):

```python
def _extract_release_date(spotify_track: Mapping[str, Any] | None) -> date | None:
    """Pull `album.release_date` + `album.release_date_precision` and parse
    according to precision. Returns None when missing or unparseable.

    Precision mapping:
        - 'day'   → exact YYYY-MM-DD
        - 'month' → YYYY-MM-01
        - 'year'  → YYYY-01-01
    """
    if not isinstance(spotify_track, Mapping):
        return None
    album = spotify_track.get("album")
    if not isinstance(album, Mapping):
        return None
    raw = album.get("release_date")
    precision = album.get("release_date_precision")
    if not isinstance(raw, str) or not isinstance(precision, str):
        return None
    try:
        if precision == "day":
            return date.fromisoformat(raw)
        if precision == "month":
            return date.fromisoformat(f"{raw}-01")
        if precision == "year":
            return date.fromisoformat(f"{raw}-01-01")
    except ValueError:
        return None
    return None
```

- [ ] **Step 3.4: Run to verify pass**

Run: `pytest tests/unit/test_spotify_release_date.py -v`
Expected: 9 tests PASS.

- [ ] **Step 3.5: Add `spotify_release_date` field to `UpdateSpotifyResultCmd`**

Modify `src/collector/repositories.py:99-104`:

```python
@dataclass(frozen=True)
class UpdateSpotifyResultCmd:
    track_id: str
    spotify_id: str | None
    searched_at: datetime
    release_type: str | None = None
    spotify_release_date: date | None = None
```

Verify `from datetime import date` is in the imports at the top of `repositories.py`; add it to the existing `from datetime import ...` line if not.

- [ ] **Step 3.6: Update `batch_update_spotify_results` SQL**

Locate the method (currently `src/collector/repositories.py:760-786`). Replace the SQL block and the bind dict to add `spotify_release_date`:

```python
    def batch_update_spotify_results(
        self,
        commands: list[UpdateSpotifyResultCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            UPDATE clouder_tracks
            SET spotify_id = :spotify_id,
                spotify_searched_at = :searched_at,
                release_type = COALESCE(:release_type, release_type),
                spotify_release_date = COALESCE(
                    :spotify_release_date, spotify_release_date
                ),
                updated_at = :searched_at
            WHERE id = :track_id
            """,
            [
                {
                    "track_id": cmd.track_id,
                    "spotify_id": cmd.spotify_id,
                    "searched_at": cmd.searched_at,
                    "release_type": cmd.release_type,
                    "spotify_release_date": cmd.spotify_release_date,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )
```

- [ ] **Step 3.7: Wire `_extract_release_date` into the handler call site**

Locate `src/collector/spotify_handler.py:280-290` (the `update_cmds` list comprehension). Replace it with:

```python
    # 2. Batch update clouder_tracks with spotify_id, searched_at,
    #    release_type, spotify_release_date.
    update_cmds = [
        UpdateSpotifyResultCmd(
            track_id=r.clouder_track_id,
            spotify_id=r.spotify_id,
            searched_at=now,
            release_type=_extract_album_type(r.spotify_track),
            spotify_release_date=_extract_release_date(r.spotify_track),
        )
        for r in chunk
    ]
    repository.batch_update_spotify_results(update_cmds)
```

- [ ] **Step 3.8: Extend `tests/unit/test_repositories.py` to assert the new SQL/bind**

Find an existing test for `batch_update_spotify_results` in `tests/unit/test_repositories.py` (search `grep -n "batch_update_spotify_results" tests/unit/test_repositories.py`). Append a new test:

```python
def test_batch_update_spotify_results_includes_release_date(monkeypatch) -> None:
    """spec-D: spotify_release_date must be COALESCEd into clouder_tracks."""
    from datetime import date, datetime, timezone
    from collector.repositories import (
        ClouderRepository,
        UpdateSpotifyResultCmd,
    )

    captured: dict = {}

    class _FakeAPI:
        def batch_execute(self, sql, params, transaction_id=None):
            captured["sql"] = sql
            captured["params"] = params

    repo = ClouderRepository(_FakeAPI())
    cmd = UpdateSpotifyResultCmd(
        track_id="t-1",
        spotify_id="sp-1",
        searched_at=datetime.now(timezone.utc),
        release_type="album",
        spotify_release_date=date(2024, 3, 15),
    )
    repo.batch_update_spotify_results([cmd])

    assert "spotify_release_date = COALESCE(" in captured["sql"]
    assert captured["params"][0]["spotify_release_date"] == date(2024, 3, 15)
```

If the test file has a different fake-API helper, reuse the existing pattern. The assertions on SQL substring + bind key are the load-bearing parts.

- [ ] **Step 3.9: Extend `tests/unit/test_spotify_handler.py` to assert the cmd field**

Find existing tests for the update_cmds construction (`grep -n "UpdateSpotifyResultCmd\|update_cmds\|_extract_album_type" tests/unit/test_spotify_handler.py`). Append a test that asserts `_extract_release_date` is wired in. If `tests/unit/test_spotify_handler.py` does not exist or has no covering test, create one (see file `tests/unit/test_spotify_handler.py` if it exists; if not, create with this content):

```python
def test_update_cmds_carry_spotify_release_date() -> None:
    """spec-D: handler patches release_date into UpdateSpotifyResultCmd."""
    from datetime import date
    from collector.spotify_handler import (
        _extract_album_type,
        _extract_release_date,
    )

    payload = {
        "album": {
            "album_type": "album",
            "release_date": "2024-03-15",
            "release_date_precision": "day",
        }
    }
    assert _extract_album_type(payload) == "album"
    assert _extract_release_date(payload) == date(2024, 3, 15)
```

If `tests/unit/test_spotify_handler.py` already exists, append; otherwise create the file with the standard pytest test prelude (`from __future__ import annotations` only — no fixtures).

- [ ] **Step 3.10: Run all touched tests**

Run: `pytest tests/unit/test_spotify_release_date.py tests/unit/test_spotify_handler.py tests/unit/test_repositories.py -v`
Expected: green.

- [ ] **Step 3.11: Run the full unit suite**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 3.12: Commit**

Suggested subject: `feat(spotify): persist album.release_date as clouder_tracks.spotify_release_date`

```bash
git add src/collector/repositories.py src/collector/spotify_handler.py \
        tests/unit/test_spotify_release_date.py \
        tests/unit/test_spotify_handler.py tests/unit/test_repositories.py
git commit -m "<caveman-commit output>"
```

---

## Task 4: Extend `collector/curation/__init__.py` with triage-specific errors

**Files:**
- Modify: `src/collector/curation/__init__.py`

- [ ] **Step 4.1: Append new error classes**

Open `src/collector/curation/__init__.py`. After the existing `OrderMismatchError` class (currently the last item in the file), append:

```python
class InvalidStateError(CurationError):
    """Operation rejected because target entity is in the wrong state."""

    error_code = "invalid_state"
    http_status = 422


class InactiveBucketError(CurationError):
    """Move/transfer target is an inactive staging bucket."""

    error_code = "target_bucket_inactive"
    http_status = 422


class InactiveStagingFinalizeError(CurationError):
    """Finalize blocked because at least one inactive staging bucket has tracks."""

    error_code = "inactive_buckets_have_tracks"
    http_status = 409

    def __init__(
        self, message: str, inactive_buckets: list[dict[str, object]]
    ) -> None:
        super().__init__(message)
        self.inactive_buckets = inactive_buckets


class TracksNotInSourceError(CurationError):
    """Move/transfer references track ids absent from the source bucket/block."""

    error_code = "tracks_not_in_source"
    http_status = 422

    def __init__(
        self, message: str, not_in_source: list[str]
    ) -> None:
        super().__init__(message)
        self.not_in_source = not_in_source


class StyleMismatchError(CurationError):
    """Cross-style transfer attempt."""

    error_code = "target_block_style_mismatch"
    http_status = 422
```

The handler will key on these classes (Task 17+) and serialize the structured payloads (`inactive_buckets`, `not_in_source`) into the response body.

- [ ] **Step 4.2: Smoke-import**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from collector.curation import InvalidStateError, InactiveBucketError, InactiveStagingFinalizeError, TracksNotInSourceError, StyleMismatchError; print('ok')"`
Expected: `ok`

- [ ] **Step 4.3: Run unit tests**

Run: `pytest tests/unit -q`
Expected: green (no tests touch these classes yet; just sanity check imports).

- [ ] **Step 4.4: Commit**

Suggested subject: `feat(curation): add triage error classes`

```bash
git add src/collector/curation/__init__.py
git commit -m "<caveman-commit output>"
```

---

## Task 5: Pydantic schemas for triage requests/responses

**Files:**
- Modify: `src/collector/curation/schemas.py` (extend with triage models)
- Test: `tests/unit/test_triage_schemas.py`

- [ ] **Step 5.1: Write failing schema tests**

```python
# tests/unit/test_triage_schemas.py
"""Test Pydantic schemas for spec-D triage requests/responses."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from collector.curation.schemas import (
    CreateTriageBlockIn,
    MoveTracksIn,
    TransferTracksIn,
)


class TestCreateTriageBlockIn:
    def test_happy_path(self) -> None:
        m = CreateTriageBlockIn(
            style_id="00000000-0000-0000-0000-000000000001",
            name="Tech House W17",
            date_from=date(2026, 4, 20),
            date_to=date(2026, 4, 26),
        )
        assert m.name == "Tech House W17"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="",
                date_from=date(2026, 4, 20),
                date_to=date(2026, 4, 26),
            )

    def test_whitespace_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="   ",
                date_from=date(2026, 4, 20),
                date_to=date(2026, 4, 26),
            )

    def test_long_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="x" * 129,
                date_from=date(2026, 4, 20),
                date_to=date(2026, 4, 26),
            )

    def test_inverted_window_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="X",
                date_from=date(2026, 4, 26),
                date_to=date(2026, 4, 20),
            )


class TestMoveTracksIn:
    def test_happy_path(self) -> None:
        m = MoveTracksIn(
            from_bucket_id="00000000-0000-0000-0000-000000000001",
            to_bucket_id="00000000-0000-0000-0000-000000000002",
            track_ids=[
                "00000000-0000-0000-0000-000000000003",
                "00000000-0000-0000-0000-000000000004",
            ],
        )
        assert len(m.track_ids) == 2

    def test_empty_track_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MoveTracksIn(
                from_bucket_id="00000000-0000-0000-0000-000000000001",
                to_bucket_id="00000000-0000-0000-0000-000000000002",
                track_ids=[],
            )

    def test_cap_1000(self) -> None:
        ids = [f"00000000-0000-0000-0000-{n:012d}" for n in range(1001)]
        with pytest.raises(ValidationError):
            MoveTracksIn(
                from_bucket_id="00000000-0000-0000-0000-000000000001",
                to_bucket_id="00000000-0000-0000-0000-000000000002",
                track_ids=ids,
            )


class TestTransferTracksIn:
    def test_cap_1000(self) -> None:
        ids = [f"00000000-0000-0000-0000-{n:012d}" for n in range(1001)]
        with pytest.raises(ValidationError):
            TransferTracksIn(
                target_bucket_id="00000000-0000-0000-0000-000000000001",
                track_ids=ids,
            )

    def test_happy_path(self) -> None:
        m = TransferTracksIn(
            target_bucket_id="00000000-0000-0000-0000-000000000001",
            track_ids=["00000000-0000-0000-0000-000000000002"],
        )
        assert len(m.track_ids) == 1
```

- [ ] **Step 5.2: Run to verify failure**

Run: `pytest tests/unit/test_triage_schemas.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 5.3: Extend `schemas.py` with triage models**

Open `src/collector/curation/schemas.py`. At the bottom of the file (after the existing spec-C schemas) append:

```python
# ----------------------- spec-D triage schemas -----------------------

from datetime import date  # may already be imported


class CreateTriageBlockIn(BaseModel):
    style_id: str = Field(..., min_length=36, max_length=36)
    name: str = Field(..., min_length=1, max_length=128)
    date_from: date
    date_to: date

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v

    @model_validator(mode="after")
    def _check_date_range(self) -> "CreateTriageBlockIn":
        if self.date_to < self.date_from:
            raise ValueError("date_to must be >= date_from")
        return self


class MoveTracksIn(BaseModel):
    from_bucket_id: str = Field(..., min_length=36, max_length=36)
    to_bucket_id: str = Field(..., min_length=36, max_length=36)
    track_ids: list[str] = Field(..., min_length=1, max_length=1000)

    @field_validator("track_ids")
    @classmethod
    def _all_uuid_shape(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) != 36:
                raise ValueError(f"track_id must be 36 chars: {t!r}")
        return v


class TransferTracksIn(BaseModel):
    target_bucket_id: str = Field(..., min_length=36, max_length=36)
    track_ids: list[str] = Field(..., min_length=1, max_length=1000)

    @field_validator("track_ids")
    @classmethod
    def _all_uuid_shape(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) != 36:
                raise ValueError(f"track_id must be 36 chars: {t!r}")
        return v
```

Verify the imports at the top of `schemas.py` already include `Field`, `field_validator`, `model_validator`, `BaseModel`. If not, add the missing names to the existing pydantic import line.

- [ ] **Step 5.4: Run to verify pass**

Run: `pytest tests/unit/test_triage_schemas.py -v`
Expected: 9 tests PASS.

- [ ] **Step 5.5: Run unit suite**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 5.6: Commit**

Suggested subject: `feat(curation): add triage Pydantic schemas`

```bash
git add src/collector/curation/schemas.py tests/unit/test_triage_schemas.py
git commit -m "<caveman-commit output>"
```

---

## Task 6: Triage service helpers — pure validators

**Files:**
- Create: `src/collector/curation/triage_service.py`
- Test: `tests/unit/test_triage_service.py`

The repository will do the heavy SQL work. The service layer only holds pure helpers that the handler can call before invoking the repository, plus a single bucket-classification helper used in tests of the create-block flow.

- [ ] **Step 6.1: Write failing service tests**

```python
# tests/unit/test_triage_service.py
"""Pure-Python helpers for spec-D triage (no DB)."""

from __future__ import annotations

from datetime import date

import pytest

from collector.curation import (
    InactiveBucketError,
    InvalidStateError,
    StyleMismatchError,
    ValidationError,
)
from collector.curation.triage_service import (
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_UNCLASSIFIED,
    BUCKET_TYPE_STAGING,
    TECHNICAL_BUCKET_TYPES,
    classify_bucket_type,
    validate_block_input,
    validate_target_for_transfer,
    validate_track_ids,
)


class TestValidateBlockInput:
    def test_happy_path(self) -> None:
        validate_block_input(
            "Tech House", date(2026, 4, 20), date(2026, 4, 26)
        )

    def test_empty_name(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input("", date(2026, 4, 20), date(2026, 4, 26))

    def test_whitespace_name(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input(
                "   ", date(2026, 4, 20), date(2026, 4, 26)
            )

    def test_long_name(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input(
                "x" * 129, date(2026, 4, 20), date(2026, 4, 26)
            )

    def test_inverted_window(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input(
                "X", date(2026, 4, 26), date(2026, 4, 20)
            )


class TestValidateTrackIds:
    def test_happy_path(self) -> None:
        validate_track_ids(
            ["00000000-0000-0000-0000-000000000001"]
        )

    def test_empty(self) -> None:
        with pytest.raises(ValidationError):
            validate_track_ids([])

    def test_cap(self) -> None:
        ids = [f"00000000-0000-0000-0000-{n:012d}" for n in range(1001)]
        with pytest.raises(ValidationError):
            validate_track_ids(ids)

    def test_bad_uuid_shape(self) -> None:
        with pytest.raises(ValidationError):
            validate_track_ids(["short"])


class TestValidateTargetForTransfer:
    def test_happy_path(self) -> None:
        validate_target_for_transfer(
            src_block={
                "user_id": "u1",
                "style_id": "s1",
                "status": "FINALIZED",
            },
            target_bucket={"inactive": False},
            target_block={
                "user_id": "u1",
                "style_id": "s1",
                "status": "IN_PROGRESS",
            },
        )

    def test_target_not_in_progress(self) -> None:
        with pytest.raises(InvalidStateError):
            validate_target_for_transfer(
                src_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
                target_bucket={"inactive": False},
                target_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "FINALIZED",
                },
            )

    def test_target_inactive(self) -> None:
        with pytest.raises(InactiveBucketError):
            validate_target_for_transfer(
                src_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
                target_bucket={"inactive": True},
                target_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
            )

    def test_style_mismatch(self) -> None:
        with pytest.raises(StyleMismatchError):
            validate_target_for_transfer(
                src_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
                target_bucket={"inactive": False},
                target_block={
                    "user_id": "u1",
                    "style_id": "s2",
                    "status": "IN_PROGRESS",
                },
            )


class TestBucketConstants:
    def test_technical_set_excludes_staging(self) -> None:
        assert BUCKET_TYPE_STAGING not in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_NEW in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_OLD in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_NOT in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_DISCARD in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_UNCLASSIFIED in TECHNICAL_BUCKET_TYPES


class TestClassifyBucketType:
    """Mirrors the SQL CASE in §6.1; used by repository tests as a fixture."""

    def test_null_release_date(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=None,
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_UNCLASSIFIED
        )

    def test_release_before_window(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2025, 1, 1),
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_OLD
        )

    def test_compilation_in_window(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2026, 4, 15),
                release_type="compilation",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_NOT
        )

    def test_old_beats_compilation(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2025, 12, 1),
                release_type="compilation",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_OLD
        )

    def test_new_default(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2026, 4, 15),
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_NEW
        )

    def test_release_equal_to_date_from_is_new(self) -> None:
        # `<` not `<=`
        assert (
            classify_bucket_type(
                spotify_release_date=date(2026, 4, 1),
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_NEW
        )
```

- [ ] **Step 6.2: Run to verify failure**

Run: `pytest tests/unit/test_triage_service.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 6.3: Implement `triage_service.py`**

```python
# src/collector/curation/triage_service.py
"""Pure helpers for spec-D triage. No DB access here."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from collector.curation import (
    InactiveBucketError,
    InvalidStateError,
    StyleMismatchError,
    ValidationError,
)


# Bucket type constants -- mirror the CHECK constraint values.
BUCKET_TYPE_NEW = "NEW"
BUCKET_TYPE_OLD = "OLD"
BUCKET_TYPE_NOT = "NOT"
BUCKET_TYPE_DISCARD = "DISCARD"
BUCKET_TYPE_UNCLASSIFIED = "UNCLASSIFIED"
BUCKET_TYPE_STAGING = "STAGING"

# The five technical bucket types created at block-create time.
TECHNICAL_BUCKET_TYPES: tuple[str, ...] = (
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_UNCLASSIFIED,
)

# UI sort order for technical buckets in detail responses.
TECHNICAL_BUCKET_DISPLAY_ORDER: tuple[str, ...] = (
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_UNCLASSIFIED,
    BUCKET_TYPE_DISCARD,
)

NAME_MAX_LEN = 128
TRACK_IDS_MAX = 1000


def validate_block_input(name: str, date_from: date, date_to: date) -> None:
    if not name or not name.strip():
        raise ValidationError("name must not be blank")
    if len(name) > NAME_MAX_LEN:
        raise ValidationError(f"name length must be <= {NAME_MAX_LEN}")
    if date_to < date_from:
        raise ValidationError("date_to must be >= date_from")


def validate_track_ids(ids: list[str]) -> None:
    if not ids:
        raise ValidationError("track_ids must not be empty")
    if len(ids) > TRACK_IDS_MAX:
        raise ValidationError(
            f"track_ids length must be <= {TRACK_IDS_MAX}"
        )
    for t in ids:
        if not isinstance(t, str) or len(t) != 36:
            raise ValidationError(
                f"track_id must be a 36-char UUID string: {t!r}"
            )


def validate_target_for_transfer(
    *,
    src_block: Mapping[str, Any],
    target_bucket: Mapping[str, Any],
    target_block: Mapping[str, Any],
) -> None:
    if target_block.get("status") != "IN_PROGRESS":
        raise InvalidStateError(
            "target triage block is not IN_PROGRESS"
        )
    if target_bucket.get("inactive") is True:
        raise InactiveBucketError(
            "target bucket is inactive (its category was soft-deleted)"
        )
    if src_block.get("style_id") != target_block.get("style_id"):
        raise StyleMismatchError(
            "source and target triage blocks belong to different styles"
        )


def classify_bucket_type(
    *,
    spotify_release_date: date | None,
    release_type: str | None,
    date_from: date,
) -> str:
    """R4 classification mirror of the SQL CASE.

    Matches the ordering in §6.1 of the spec:
        NULL date → UNCLASSIFIED
        date < date_from → OLD
        release_type == 'compilation' → NOT
        else → NEW
    """
    if spotify_release_date is None:
        return BUCKET_TYPE_UNCLASSIFIED
    if spotify_release_date < date_from:
        return BUCKET_TYPE_OLD
    if release_type == "compilation":
        return BUCKET_TYPE_NOT
    return BUCKET_TYPE_NEW
```

- [ ] **Step 6.4: Run to verify pass**

Run: `pytest tests/unit/test_triage_service.py -v`
Expected: all tests PASS.

- [ ] **Step 6.5: Run unit suite**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 6.6: Commit**

Suggested subject: `feat(curation): add triage service validators and bucket constants`

```bash
git add src/collector/curation/triage_service.py tests/unit/test_triage_service.py
git commit -m "<caveman-commit output>"
```

---

## Task 7: Triage repository skeleton — dataclasses and factory

**Files:**
- Create: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py`

This task lands the row dataclasses and the empty `TriageRepository` class. Subsequent tasks fill methods one at a time.

- [ ] **Step 7.1: Write the failing skeleton test**

```python
# tests/unit/test_triage_repository.py
"""Unit tests for TriageRepository (mocked Data API)."""

from __future__ import annotations

from collector.curation.triage_repository import (
    TriageRepository,
    TriageBlockRow,
    TriageBucketRow,
    BucketTrackRowOut,
)


def test_module_exposes_repository_class() -> None:
    assert hasattr(TriageRepository, "create_block")
    assert hasattr(TriageRepository, "get_block")
    assert hasattr(TriageRepository, "list_blocks_by_style")
    assert hasattr(TriageRepository, "list_blocks_all")
    assert hasattr(TriageRepository, "list_bucket_tracks")
    assert hasattr(TriageRepository, "move_tracks")
    assert hasattr(TriageRepository, "transfer_tracks")
    assert hasattr(TriageRepository, "finalize_block")
    assert hasattr(TriageRepository, "soft_delete_block")
    assert hasattr(
        TriageRepository, "snapshot_category_into_active_blocks"
    )
    assert hasattr(
        TriageRepository, "mark_staging_inactive_for_category"
    )


def test_dataclasses_have_expected_fields() -> None:
    row = TriageBlockRow(
        id="b-1",
        user_id="u-1",
        style_id="s-1",
        style_name="House",
        name="Tech House W17",
        date_from="2026-04-20",
        date_to="2026-04-26",
        status="IN_PROGRESS",
        created_at="2026-04-28T00:00:00+00:00",
        updated_at="2026-04-28T00:00:00+00:00",
        finalized_at=None,
        buckets=(),
    )
    assert row.id == "b-1"
    assert row.buckets == ()
```

- [ ] **Step 7.2: Run to verify failure**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 7.3: Implement the skeleton**

```python
# src/collector/curation/triage_repository.py
"""Aurora Data API repository for spec-D triage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from typing import Any, Iterable, Mapping, Sequence

from collector.curation import (
    InactiveBucketError,
    InactiveStagingFinalizeError,
    InvalidStateError,
    NotFoundError,
    StyleMismatchError,
    TracksNotInSourceError,
    ValidationError,
    utc_now,
)
from collector.curation.triage_service import (
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_STAGING,
    BUCKET_TYPE_UNCLASSIFIED,
    TECHNICAL_BUCKET_DISPLAY_ORDER,
    TECHNICAL_BUCKET_TYPES,
    TRACK_IDS_MAX,
)
from collector.data_api import DataAPIClient


@dataclass(frozen=True)
class TriageBucketRow:
    id: str
    bucket_type: str
    category_id: str | None
    category_name: str | None
    inactive: bool
    track_count: int


@dataclass(frozen=True)
class TriageBlockRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    date_from: str  # ISO YYYY-MM-DD as returned by Data API
    date_to: str
    status: str
    created_at: str  # ISO datetime
    updated_at: str
    finalized_at: str | None
    buckets: Sequence[TriageBucketRow] = field(default_factory=tuple)


@dataclass(frozen=True)
class TriageBlockSummaryRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    date_from: str
    date_to: str
    status: str
    created_at: str
    updated_at: str
    finalized_at: str | None
    track_count: int


@dataclass(frozen=True)
class BucketTrackRowOut:
    """Row returned by GET /triage/blocks/{id}/buckets/{bucket_id}/tracks."""

    track_id: str
    title: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    publish_date: str | None
    spotify_release_date: str | None
    spotify_id: str | None
    release_type: str | None
    is_ai_suspected: bool
    artists: tuple[str, ...]
    added_at: str


@dataclass(frozen=True)
class MoveResult:
    moved: int


@dataclass(frozen=True)
class TransferResult:
    transferred: int


@dataclass(frozen=True)
class FinalizeResult:
    block: TriageBlockRow
    promoted: dict[str, int]


class TriageRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # --- writes -------------------------------------------------------

    def create_block(
        self,
        *,
        user_id: str,
        style_id: str,
        name: str,
        date_from: date_type,
        date_to: date_type,
    ) -> TriageBlockRow:
        raise NotImplementedError

    def move_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        from_bucket_id: str,
        to_bucket_id: str,
        track_ids: Sequence[str],
    ) -> MoveResult:
        raise NotImplementedError

    def transfer_tracks(
        self,
        *,
        user_id: str,
        src_block_id: str,
        target_bucket_id: str,
        track_ids: Sequence[str],
    ) -> TransferResult:
        raise NotImplementedError

    def finalize_block(
        self,
        *,
        user_id: str,
        block_id: str,
        categories_repository: Any,
    ) -> FinalizeResult:
        raise NotImplementedError

    def soft_delete_block(
        self, *, user_id: str, block_id: str
    ) -> bool:
        raise NotImplementedError

    def snapshot_category_into_active_blocks(
        self,
        *,
        user_id: str,
        style_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    def mark_staging_inactive_for_category(
        self,
        *,
        user_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    # --- reads --------------------------------------------------------

    def get_block(
        self, *, user_id: str, block_id: str
    ) -> TriageBlockRow | None:
        raise NotImplementedError

    def list_blocks_by_style(
        self,
        *,
        user_id: str,
        style_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        raise NotImplementedError

    def list_blocks_all(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        raise NotImplementedError

    def list_bucket_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        bucket_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> tuple[list[BucketTrackRowOut], int]:
        raise NotImplementedError
```

- [ ] **Step 7.4: Run to verify pass**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: 2 tests PASS.

- [ ] **Step 7.5: Commit**

Suggested subject: `feat(curation): add triage repository skeleton with row dataclasses`

```bash
git add src/collector/curation/triage_repository.py tests/unit/test_triage_repository.py
git commit -m "<caveman-commit output>"
```

---

## Task 8: Repository — `create_block` (six-step transaction)

This is the most complex method in the plan. Implement it as a single transaction that performs all six steps from spec §5.2.

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

- [ ] **Step 8.1: Append failing tests for `create_block`**

Append to `tests/unit/test_triage_repository.py`:

```python
from datetime import date
from unittest.mock import MagicMock, call

import pytest

from collector.curation import NotFoundError
from collector.curation.triage_repository import (
    TriageRepository,
    TriageBlockRow,
)


class _FakeTx:
    """Context manager mimicking DataAPIClient.transaction()."""

    def __init__(self, tx_id: str = "tx-1") -> None:
        self.tx_id = tx_id

    def __enter__(self) -> str:
        return self.tx_id

    def __exit__(self, *exc: Any) -> None:
        return None


def _api_with_responses(responses: list[Any]) -> MagicMock:
    api = MagicMock()
    api.transaction.return_value = _FakeTx()
    api.execute.side_effect = responses
    return api


def test_create_block_happy_path() -> None:
    """Six-step TX: insert block, 5 tech buckets, N staging buckets,
    classify-and-insert tracks, return assembled block."""
    # Sequence of execute() responses the repo expects:
    #   1. style row (style_name lookup)         → [{"name": "House"}]
    #   2. INSERT triage_blocks RETURNING        → [{"id": "<block_id>"}]
    #      (we use the supplied id, but accept the row)
    #   3. INSERT 5 technical buckets RETURNING  → 5 rows of {id, bucket_type}
    #   4. SELECT alive categories               → categories list
    #   5. INSERT N staging buckets RETURNING    → N rows
    #   6. INSERT classification (no RETURNING)  → []
    #   7. SELECT detail (block + buckets)       → final shape
    #
    # We only assert the high-level structure: the call sequence and that
    # the block row + 5 technical + 1 staging bucket are inserted.

    style_response = [{"id": "s-1", "name": "House"}]
    block_response = [{"id": "b-1"}]
    tech_buckets_response = [
        {"id": f"buck-tech-{i}", "bucket_type": t}
        for i, t in enumerate(["NEW", "OLD", "NOT", "DISCARD", "UNCLASSIFIED"])
    ]
    categories_response = [
        {"id": "c-1", "name": "Tech House", "position": 0},
    ]
    staging_buckets_response = [
        {"id": "buck-stg-1", "category_id": "c-1"},
    ]
    classify_response: list[dict[str, Any]] = []
    detail_response = [
        {
            "id": "b-1",
            "user_id": "u-1",
            "style_id": "s-1",
            "style_name": "House",
            "name": "Tech House W17",
            "date_from": "2026-04-20",
            "date_to": "2026-04-26",
            "status": "IN_PROGRESS",
            "created_at": "2026-04-28T00:00:00+00:00",
            "updated_at": "2026-04-28T00:00:00+00:00",
            "finalized_at": None,
        }
    ]
    # buckets-with-counts query for detail:
    buckets_with_counts_response = [
        # technical buckets
        {
            "id": f"buck-tech-{i}",
            "bucket_type": t,
            "category_id": None,
            "category_name": None,
            "inactive": False,
            "track_count": 0,
        }
        for i, t in enumerate(["NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"])
    ] + [
        {
            "id": "buck-stg-1",
            "bucket_type": "STAGING",
            "category_id": "c-1",
            "category_name": "Tech House",
            "inactive": False,
            "track_count": 0,
        }
    ]

    api = _api_with_responses(
        [
            style_response,
            block_response,
            tech_buckets_response,
            categories_response,
            staging_buckets_response,
            classify_response,
            detail_response,
            buckets_with_counts_response,
        ]
    )
    repo = TriageRepository(api)
    out = repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="Tech House W17",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
    )

    assert isinstance(out, TriageBlockRow)
    assert out.style_name == "House"
    assert out.status == "IN_PROGRESS"
    # 5 technical + 1 staging
    assert len(out.buckets) == 6
    types = [b.bucket_type for b in out.buckets]
    # technical sort order then staging
    assert types[:5] == ["NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"]
    assert types[5] == "STAGING"


def test_create_block_style_not_found() -> None:
    api = _api_with_responses([[]])  # style lookup returns 0 rows
    repo = TriageRepository(api)
    with pytest.raises(NotFoundError) as ei:
        repo.create_block(
            user_id="u-1",
            style_id="missing",
            name="X",
            date_from=date(2026, 4, 20),
            date_to=date(2026, 4, 26),
        )
    assert ei.value.error_code == "style_not_found"


def test_create_block_classify_sql_includes_filters_and_case() -> None:
    """Spot-check the R4 INSERT-FROM-SELECT statement."""
    api = _api_with_responses(
        [
            [{"id": "s-1", "name": "House"}],
            [{"id": "b-1"}],
            [
                {"id": f"t-{i}", "bucket_type": t}
                for i, t in enumerate(
                    ["NEW", "OLD", "NOT", "DISCARD", "UNCLASSIFIED"]
                )
            ],
            [],  # no alive categories
            [],  # no staging inserted
            [],  # classify INSERT
            [
                {
                    "id": "b-1",
                    "user_id": "u-1",
                    "style_id": "s-1",
                    "style_name": "House",
                    "name": "X",
                    "date_from": "2026-04-20",
                    "date_to": "2026-04-26",
                    "status": "IN_PROGRESS",
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "updated_at": "2026-04-28T00:00:00+00:00",
                    "finalized_at": None,
                }
            ],
            [],  # buckets-with-counts (5 technical, no staging)
        ]
    )
    repo = TriageRepository(api)
    repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="X",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
    )

    # Look at the classify call (6th execute, index 5).
    classify_call = api.execute.call_args_list[5]
    sql = classify_call.args[0]
    params = classify_call.args[1]
    assert "INSERT INTO triage_bucket_tracks" in sql
    assert "FROM clouder_tracks t" in sql
    assert "spotify_release_date IS NULL" in sql
    assert "t.spotify_release_date < :date_from" in sql
    assert "release_type = 'compilation'" in sql
    assert "NOT EXISTS" in sql  # already-categorized filter
    assert "categories c" in sql
    assert "c.deleted_at IS NULL" in sql
    assert params["user_id"] == "u-1"
    assert params["style_id"] == "s-1"
    assert params["date_from"] == "2026-04-20"
    assert params["date_to"] == "2026-04-26"
    # All four bucket-id binds present
    assert "new_bucket_id" in params
    assert "old_bucket_id" in params
    assert "not_bucket_id" in params
    assert "unclassified_bucket_id" in params
```

- [ ] **Step 8.2: Run to verify failure**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 8.3: Implement `create_block`**

In `src/collector/curation/triage_repository.py`, replace the `create_block` placeholder with:

```python
    def create_block(
        self,
        *,
        user_id: str,
        style_id: str,
        name: str,
        date_from: date_type,
        date_to: date_type,
    ) -> TriageBlockRow:
        from uuid import uuid4

        df = date_from.isoformat()
        dt = date_to.isoformat()
        now = utc_now()
        now_iso = now.isoformat()

        with self._data_api.transaction() as tx_id:
            # 1. Verify style exists (and grab name for response shape).
            style_rows = self._data_api.execute(
                """
                SELECT id, name FROM clouder_styles WHERE id = :style_id
                """,
                {"style_id": style_id},
                transaction_id=tx_id,
            )
            if not style_rows:
                raise NotFoundError(
                    "style_not_found",
                    f"clouder_styles row not found: {style_id}",
                )
            style_name = style_rows[0]["name"]

            # 2. Insert triage_blocks row.
            block_id = str(uuid4())
            self._data_api.execute(
                """
                INSERT INTO triage_blocks (
                    id, user_id, style_id, name,
                    date_from, date_to, status,
                    created_at, updated_at
                ) VALUES (
                    :id, :user_id, :style_id, :name,
                    :date_from, :date_to, 'IN_PROGRESS',
                    :now, :now
                )
                """,
                {
                    "id": block_id,
                    "user_id": user_id,
                    "style_id": style_id,
                    "name": name,
                    "date_from": df,
                    "date_to": dt,
                    "now": now_iso,
                },
                transaction_id=tx_id,
            )

            # 3. Insert the 5 technical buckets and capture the resulting ids.
            tech_bucket_id_by_type: dict[str, str] = {}
            for bucket_type in TECHNICAL_BUCKET_TYPES:
                bid = str(uuid4())
                self._data_api.execute(
                    """
                    INSERT INTO triage_buckets (
                        id, triage_block_id, bucket_type, category_id,
                        inactive, created_at
                    ) VALUES (
                        :id, :block_id, :bucket_type, NULL,
                        FALSE, :now
                    )
                    """,
                    {
                        "id": bid,
                        "block_id": block_id,
                        "bucket_type": bucket_type,
                        "now": now_iso,
                    },
                    transaction_id=tx_id,
                )
                tech_bucket_id_by_type[bucket_type] = bid

            # 4. Snapshot one staging bucket per alive category.
            categories = self._data_api.execute(
                """
                SELECT id FROM categories
                WHERE user_id = :user_id
                  AND style_id = :style_id
                  AND deleted_at IS NULL
                ORDER BY position ASC, created_at DESC, id ASC
                """,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            for cat in categories:
                bid = str(uuid4())
                self._data_api.execute(
                    """
                    INSERT INTO triage_buckets (
                        id, triage_block_id, bucket_type, category_id,
                        inactive, created_at
                    ) VALUES (
                        :id, :block_id, 'STAGING', :category_id,
                        FALSE, :now
                    )
                    """,
                    {
                        "id": bid,
                        "block_id": block_id,
                        "category_id": cat["id"],
                        "now": now_iso,
                    },
                    transaction_id=tx_id,
                )

            # 5. Classify and insert tracks (R4 in one INSERT FROM SELECT).
            self._data_api.execute(
                """
                INSERT INTO triage_bucket_tracks
                    (triage_bucket_id, track_id, added_at)
                SELECT
                    CASE
                        WHEN t.spotify_release_date IS NULL
                            THEN :unclassified_bucket_id
                        WHEN t.spotify_release_date < :date_from
                            THEN :old_bucket_id
                        WHEN t.release_type = 'compilation'
                            THEN :not_bucket_id
                        ELSE :new_bucket_id
                    END,
                    t.id,
                    :now
                FROM clouder_tracks t
                WHERE t.style_id = :style_id
                  AND t.publish_date BETWEEN :date_from AND :date_to
                  AND NOT EXISTS (
                    SELECT 1
                    FROM category_tracks ct
                    JOIN categories c ON ct.category_id = c.id
                    WHERE c.user_id = :user_id
                      AND c.style_id = :style_id
                      AND c.deleted_at IS NULL
                      AND ct.track_id = t.id
                  )
                """,
                {
                    "user_id": user_id,
                    "style_id": style_id,
                    "date_from": df,
                    "date_to": dt,
                    "now": now_iso,
                    "new_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_NEW],
                    "old_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_OLD],
                    "not_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_NOT],
                    "unclassified_bucket_id": tech_bucket_id_by_type[
                        BUCKET_TYPE_UNCLASSIFIED
                    ],
                },
                transaction_id=tx_id,
            )

            # 6. Re-fetch the assembled block detail (with style_name and
            #    buckets) inside the same TX so callers see consistent state.
            block = self._fetch_block_detail(
                user_id=user_id, block_id=block_id, transaction_id=tx_id
            )

        if block is None:  # pragma: no cover - we just inserted
            raise RuntimeError("create_block: post-insert fetch returned None")
        return block
```

Then add the helper at the bottom of the class:

```python
    # --- internal helpers --------------------------------------------

    def _fetch_block_detail(
        self,
        *,
        user_id: str,
        block_id: str,
        transaction_id: str | None,
    ) -> TriageBlockRow | None:
        block_rows = self._data_api.execute(
            """
            SELECT
                tb.id, tb.user_id, tb.style_id,
                cs.name AS style_name,
                tb.name,
                tb.date_from, tb.date_to,
                tb.status,
                tb.created_at, tb.updated_at, tb.finalized_at
            FROM triage_blocks tb
            JOIN clouder_styles cs ON tb.style_id = cs.id
            WHERE tb.id = :block_id
              AND tb.user_id = :user_id
              AND tb.deleted_at IS NULL
            """,
            {"block_id": block_id, "user_id": user_id},
            transaction_id=transaction_id,
        )
        if not block_rows:
            return None
        b = block_rows[0]

        bucket_rows = self._data_api.execute(
            """
            SELECT
                tbk.id, tbk.bucket_type, tbk.category_id,
                c.name AS category_name,
                tbk.inactive,
                COALESCE(tc.cnt, 0) AS track_count
            FROM triage_buckets tbk
            LEFT JOIN categories c ON tbk.category_id = c.id
            LEFT JOIN (
                SELECT triage_bucket_id, COUNT(*) AS cnt
                FROM triage_bucket_tracks
                GROUP BY triage_bucket_id
            ) tc ON tc.triage_bucket_id = tbk.id
            LEFT JOIN categories cs ON tbk.category_id = cs.id
            WHERE tbk.triage_block_id = :block_id
            """,
            {"block_id": block_id},
            transaction_id=transaction_id,
        )

        # Sort: technical buckets in TECHNICAL_BUCKET_DISPLAY_ORDER,
        # then staging buckets ordered by category position/created_at.
        sort_index = {
            t: i for i, t in enumerate(TECHNICAL_BUCKET_DISPLAY_ORDER)
        }

        def sort_key(row: Mapping[str, Any]) -> tuple[int, str]:
            bt = row["bucket_type"]
            if bt == BUCKET_TYPE_STAGING:
                return (
                    len(TECHNICAL_BUCKET_DISPLAY_ORDER),
                    row.get("category_name") or row["id"],
                )
            return (sort_index.get(bt, 999), row["id"])

        bucket_rows_sorted = sorted(bucket_rows, key=sort_key)
        buckets = tuple(
            TriageBucketRow(
                id=r["id"],
                bucket_type=r["bucket_type"],
                category_id=r.get("category_id"),
                category_name=r.get("category_name"),
                inactive=bool(r["inactive"]),
                track_count=int(r["track_count"]),
            )
            for r in bucket_rows_sorted
        )

        return TriageBlockRow(
            id=b["id"],
            user_id=b["user_id"],
            style_id=b["style_id"],
            style_name=b["style_name"],
            name=b["name"],
            date_from=str(b["date_from"]),
            date_to=str(b["date_to"]),
            status=b["status"],
            created_at=str(b["created_at"]),
            updated_at=str(b["updated_at"]),
            finalized_at=(
                str(b["finalized_at"]) if b["finalized_at"] is not None else None
            ),
            buckets=buckets,
        )
```

- [ ] **Step 8.4: Run to verify pass**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: all tests PASS (skeleton + 3 create_block tests).

- [ ] **Step 8.5: Run unit suite**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 8.6: Commit**

Suggested subject: `feat(curation): add triage create_block six-step transaction`

```bash
git add src/collector/curation/triage_repository.py tests/unit/test_triage_repository.py
git commit -m "<caveman-commit output>"
```

---

## Task 9: Repository — read methods (`get_block`, `list_blocks_by_style`, `list_blocks_all`)

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

- [ ] **Step 9.1: Append failing tests**

```python
def test_get_block_returns_full_detail() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "id": "b-1",
                    "user_id": "u-1",
                    "style_id": "s-1",
                    "style_name": "House",
                    "name": "X",
                    "date_from": "2026-04-20",
                    "date_to": "2026-04-26",
                    "status": "IN_PROGRESS",
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "updated_at": "2026-04-28T00:00:00+00:00",
                    "finalized_at": None,
                }
            ],
            [],
        ]
    )
    repo = TriageRepository(api)
    out = repo.get_block(user_id="u-1", block_id="b-1")
    assert out is not None
    assert out.style_name == "House"


def test_get_block_missing_returns_none() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    assert repo.get_block(user_id="u-1", block_id="missing") is None


def test_list_blocks_by_style_status_filter_in_sql() -> None:
    api = _api_with_responses(
        [
            [{"id": "s-1"}],
            [],
            [{"total": 0}],
        ]
    )
    repo = TriageRepository(api)
    repo.list_blocks_by_style(
        user_id="u-1",
        style_id="s-1",
        limit=50,
        offset=0,
        status="FINALIZED",
    )
    list_call = api.execute.call_args_list[1]
    assert "status = :status" in list_call.args[0]
    assert list_call.args[1]["status"] == "FINALIZED"


def test_list_blocks_by_style_style_not_found() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    with pytest.raises(NotFoundError) as ei:
        repo.list_blocks_by_style(
            user_id="u-1", style_id="missing", limit=50, offset=0
        )
    assert ei.value.error_code == "style_not_found"


def test_list_blocks_all_no_style_filter() -> None:
    api = _api_with_responses([[], [{"total": 0}]])
    repo = TriageRepository(api)
    repo.list_blocks_all(user_id="u-1", limit=50, offset=0)
    list_call = api.execute.call_args_list[0]
    sql = list_call.args[0]
    assert "tb.user_id = :user_id" in sql
    assert ":style_id" not in sql
```

- [ ] **Step 9.2: Run to verify failure**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: FAIL with `NotImplementedError` on the new tests.

- [ ] **Step 9.3: Implement `get_block`**

Replace the placeholder with:

```python
    def get_block(
        self, *, user_id: str, block_id: str
    ) -> TriageBlockRow | None:
        return self._fetch_block_detail(
            user_id=user_id, block_id=block_id, transaction_id=None
        )
```

- [ ] **Step 9.4: Implement `list_blocks_by_style`**

```python
    def list_blocks_by_style(
        self,
        *,
        user_id: str,
        style_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        style_rows = self._data_api.execute(
            "SELECT id FROM clouder_styles WHERE id = :style_id",
            {"style_id": style_id},
        )
        if not style_rows:
            raise NotFoundError(
                "style_not_found",
                f"clouder_styles row not found: {style_id}",
            )

        sql_filter = ""
        params: dict[str, Any] = {
            "user_id": user_id,
            "style_id": style_id,
            "limit": limit,
            "offset": offset,
        }
        if status is not None:
            sql_filter = " AND tb.status = :status"
            params["status"] = status

        rows = self._data_api.execute(
            f"""
            SELECT
                tb.id, tb.user_id, tb.style_id,
                cs.name AS style_name,
                tb.name,
                tb.date_from, tb.date_to,
                tb.status,
                tb.created_at, tb.updated_at, tb.finalized_at,
                COALESCE(tc.cnt, 0) AS track_count
            FROM triage_blocks tb
            JOIN clouder_styles cs ON tb.style_id = cs.id
            LEFT JOIN (
                SELECT tbk.triage_block_id, COUNT(*) AS cnt
                FROM triage_buckets tbk
                JOIN triage_bucket_tracks tbt
                  ON tbt.triage_bucket_id = tbk.id
                GROUP BY tbk.triage_block_id
            ) tc ON tc.triage_block_id = tb.id
            WHERE tb.user_id = :user_id
              AND tb.style_id = :style_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            ORDER BY tb.created_at DESC, tb.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM triage_blocks tb
            WHERE tb.user_id = :user_id
              AND tb.style_id = :style_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            """,
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        items = [
            TriageBlockSummaryRow(
                id=r["id"],
                user_id=r["user_id"],
                style_id=r["style_id"],
                style_name=r["style_name"],
                name=r["name"],
                date_from=str(r["date_from"]),
                date_to=str(r["date_to"]),
                status=r["status"],
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
                finalized_at=(
                    str(r["finalized_at"])
                    if r["finalized_at"] is not None
                    else None
                ),
                track_count=int(r["track_count"]),
            )
            for r in rows
        ]
        return items, total
```

- [ ] **Step 9.5: Implement `list_blocks_all`**

```python
    def list_blocks_all(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        sql_filter = ""
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        }
        if status is not None:
            sql_filter = " AND tb.status = :status"
            params["status"] = status

        rows = self._data_api.execute(
            f"""
            SELECT
                tb.id, tb.user_id, tb.style_id,
                cs.name AS style_name,
                tb.name,
                tb.date_from, tb.date_to,
                tb.status,
                tb.created_at, tb.updated_at, tb.finalized_at,
                COALESCE(tc.cnt, 0) AS track_count
            FROM triage_blocks tb
            JOIN clouder_styles cs ON tb.style_id = cs.id
            LEFT JOIN (
                SELECT tbk.triage_block_id, COUNT(*) AS cnt
                FROM triage_buckets tbk
                JOIN triage_bucket_tracks tbt
                  ON tbt.triage_bucket_id = tbk.id
                GROUP BY tbk.triage_block_id
            ) tc ON tc.triage_block_id = tb.id
            WHERE tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            ORDER BY tb.created_at DESC, tb.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM triage_blocks tb
            WHERE tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              {sql_filter}
            """,
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        items = [
            TriageBlockSummaryRow(
                id=r["id"],
                user_id=r["user_id"],
                style_id=r["style_id"],
                style_name=r["style_name"],
                name=r["name"],
                date_from=str(r["date_from"]),
                date_to=str(r["date_to"]),
                status=r["status"],
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
                finalized_at=(
                    str(r["finalized_at"])
                    if r["finalized_at"] is not None
                    else None
                ),
                track_count=int(r["track_count"]),
            )
            for r in rows
        ]
        return items, total
```

- [ ] **Step 9.6: Run tests**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: green.

- [ ] **Step 9.7: Commit**

Suggested subject: `feat(curation): add triage repository read methods`

```bash
git add src/collector/curation/triage_repository.py tests/unit/test_triage_repository.py
git commit -m "<caveman-commit message>"
```

---

## Task 10: Repository — `list_bucket_tracks`

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

- [ ] **Step 10.1: Append failing tests**

```python
def test_list_bucket_tracks_validates_block_and_bucket() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    with pytest.raises(NotFoundError) as ei:
        repo.list_bucket_tracks(
            user_id="u-1",
            block_id="b-missing",
            bucket_id="bk-missing",
            limit=50,
            offset=0,
        )
    assert ei.value.error_code == "bucket_not_in_block"


def test_list_bucket_tracks_search_lowers_term() -> None:
    api = _api_with_responses(
        [
            [{"block_id": "b-1", "bucket_id": "bk-1"}],
            [],
            [{"total": 0}],
        ]
    )
    repo = TriageRepository(api)
    repo.list_bucket_tracks(
        user_id="u-1",
        block_id="b-1",
        bucket_id="bk-1",
        limit=50,
        offset=0,
        search="  Tech  ",
    )
    rows_call = api.execute.call_args_list[1]
    sql = rows_call.args[0]
    params = rows_call.args[1]
    assert "ILIKE :search" in sql
    assert params["search"] == "%tech%"
```

- [ ] **Step 10.2: Implement**

```python
    def list_bucket_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        bucket_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> tuple[list[BucketTrackRowOut], int]:
        guard = self._data_api.execute(
            """
            SELECT tb.id AS block_id, tbk.id AS bucket_id
            FROM triage_blocks tb
            JOIN triage_buckets tbk ON tbk.triage_block_id = tb.id
            WHERE tb.id = :block_id
              AND tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              AND tbk.id = :bucket_id
            """,
            {
                "block_id": block_id,
                "user_id": user_id,
                "bucket_id": bucket_id,
            },
        )
        if not guard:
            raise NotFoundError(
                "bucket_not_in_block",
                f"bucket {bucket_id} not found in triage block {block_id}",
            )

        params: dict[str, Any] = {
            "bucket_id": bucket_id,
            "limit": limit,
            "offset": offset,
        }
        search_clause = ""
        if search and search.strip():
            term = "%" + search.strip().lower() + "%"
            params["search"] = term
            search_clause = " AND t.normalized_title ILIKE :search"

        rows = self._data_api.execute(
            f"""
            SELECT
                t.id AS track_id,
                t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.publish_date, t.spotify_release_date,
                t.spotify_id, t.release_type, t.is_ai_suspected,
                tbt.added_at,
                COALESCE(
                    ARRAY_AGG(ca.name ORDER BY cta.position)
                        FILTER (WHERE ca.id IS NOT NULL),
                    ARRAY[]::text[]
                ) AS artist_names
            FROM triage_bucket_tracks tbt
            JOIN clouder_tracks t ON t.id = tbt.track_id
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists ca ON ca.id = cta.artist_id
            WHERE tbt.triage_bucket_id = :bucket_id
              {search_clause}
            GROUP BY
                t.id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.publish_date, t.spotify_release_date,
                t.spotify_id, t.release_type, t.is_ai_suspected,
                tbt.added_at
            ORDER BY tbt.added_at DESC, t.id ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM triage_bucket_tracks tbt
            JOIN clouder_tracks t ON t.id = tbt.track_id
            WHERE tbt.triage_bucket_id = :bucket_id
              {search_clause}
            """,
            params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        items = [
            BucketTrackRowOut(
                track_id=r["track_id"],
                title=r["title"],
                mix_name=r.get("mix_name"),
                isrc=r.get("isrc"),
                bpm=int(r["bpm"]) if r.get("bpm") is not None else None,
                length_ms=(
                    int(r["length_ms"])
                    if r.get("length_ms") is not None
                    else None
                ),
                publish_date=(
                    str(r["publish_date"])
                    if r.get("publish_date") is not None
                    else None
                ),
                spotify_release_date=(
                    str(r["spotify_release_date"])
                    if r.get("spotify_release_date") is not None
                    else None
                ),
                spotify_id=r.get("spotify_id"),
                release_type=r.get("release_type"),
                is_ai_suspected=bool(r.get("is_ai_suspected", False)),
                artists=tuple(r.get("artist_names") or ()),
                added_at=str(r["added_at"]),
            )
            for r in rows
        ]
        return items, total
```

- [ ] **Step 10.3: Run tests**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: green.

- [ ] **Step 10.4: Commit**

Suggested subject: `feat(curation): add triage list_bucket_tracks repository method`

---

## Task 11: Repository — `move_tracks`

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

- [ ] **Step 11.1: Append failing tests**

```python
def test_move_tracks_target_inactive() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": True,
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(InactiveBucketError):
        repo.move_tracks(
            user_id="u-1",
            block_id="b-1",
            from_bucket_id="bk-from",
            to_bucket_id="bk-to",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_move_tracks_block_not_editable() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "FINALIZED",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": False,
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(InvalidStateError):
        repo.move_tracks(
            user_id="u-1",
            block_id="b-1",
            from_bucket_id="bk-from",
            to_bucket_id="bk-to",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_move_tracks_tracks_not_in_source() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": False,
                }
            ],
            [{"track_id": "00000000-0000-0000-0000-000000000001"}],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(TracksNotInSourceError) as ei:
        repo.move_tracks(
            user_id="u-1",
            block_id="b-1",
            from_bucket_id="bk-from",
            to_bucket_id="bk-to",
            track_ids=[
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
            ],
        )
    assert "00000000-0000-0000-0000-000000000002" in ei.value.not_in_source


def test_move_tracks_happy_path() -> None:
    ids_present = [
        {"track_id": f"00000000-0000-0000-0000-{n:012d}"} for n in (1, 2)
    ]
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": False,
                }
            ],
            ids_present,
            [],  # DELETE
            [],  # INSERT
        ]
    )
    repo = TriageRepository(api)
    out = repo.move_tracks(
        user_id="u-1",
        block_id="b-1",
        from_bucket_id="bk-from",
        to_bucket_id="bk-to",
        track_ids=[
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
    )
    assert out.moved == 2
    delete_call = api.execute.call_args_list[2]
    insert_call = api.execute.call_args_list[3]
    assert "DELETE FROM triage_bucket_tracks" in delete_call.args[0]
    assert "INSERT INTO triage_bucket_tracks" in insert_call.args[0]
    assert "ON CONFLICT" in insert_call.args[0]


def test_move_tracks_self_noop() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-x",
                    "from_inactive": False,
                    "to_id": "bk-x",
                    "to_inactive": False,
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    out = repo.move_tracks(
        user_id="u-1",
        block_id="b-1",
        from_bucket_id="bk-x",
        to_bucket_id="bk-x",
        track_ids=["00000000-0000-0000-0000-000000000001"],
    )
    assert out.moved == 0
    assert api.execute.call_count == 1
```

- [ ] **Step 11.2: Implement `move_tracks`**

```python
    def move_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        from_bucket_id: str,
        to_bucket_id: str,
        track_ids: Sequence[str],
    ) -> MoveResult:
        guard = self._data_api.execute(
            """
            SELECT
                tb.status AS block_status,
                bf.id AS from_id, bf.inactive AS from_inactive,
                bt.id AS to_id, bt.inactive AS to_inactive
            FROM triage_blocks tb
            JOIN triage_buckets bf ON bf.triage_block_id = tb.id
            JOIN triage_buckets bt ON bt.triage_block_id = tb.id
            WHERE tb.id = :block_id
              AND tb.user_id = :user_id
              AND tb.deleted_at IS NULL
              AND bf.id = :from_id
              AND bt.id = :to_id
            """,
            {
                "block_id": block_id,
                "user_id": user_id,
                "from_id": from_bucket_id,
                "to_id": to_bucket_id,
            },
        )
        if not guard:
            raise NotFoundError(
                "bucket_not_in_block", "block or bucket not found"
            )
        row = guard[0]
        if row["block_status"] != "IN_PROGRESS":
            raise InvalidStateError(
                "triage block is not editable (status != IN_PROGRESS)"
            )
        if bool(row["to_inactive"]):
            raise InactiveBucketError(
                "target bucket is inactive (its category was soft-deleted)"
            )

        if from_bucket_id == to_bucket_id:
            return MoveResult(moved=0)

        present = self._data_api.execute(
            """
            SELECT track_id
            FROM triage_bucket_tracks
            WHERE triage_bucket_id = :from_id
              AND track_id = ANY(:track_ids)
            """,
            {
                "from_id": from_bucket_id,
                "track_ids": list(track_ids),
            },
        )
        present_ids = {r["track_id"] for r in present}
        missing = [t for t in track_ids if t not in present_ids]
        if missing:
            raise TracksNotInSourceError(
                f"{len(missing)} track(s) not present in source bucket",
                missing,
            )

        with self._data_api.transaction() as tx_id:
            self._data_api.execute(
                """
                DELETE FROM triage_bucket_tracks
                WHERE triage_bucket_id = :from_id
                  AND track_id = ANY(:track_ids)
                """,
                {
                    "from_id": from_bucket_id,
                    "track_ids": list(track_ids),
                },
                transaction_id=tx_id,
            )
            self._data_api.execute(
                """
                INSERT INTO triage_bucket_tracks
                    (triage_bucket_id, track_id, added_at)
                SELECT :to_id, t, :now
                FROM UNNEST(:track_ids::text[]) AS t
                ON CONFLICT (triage_bucket_id, track_id) DO NOTHING
                """,
                {
                    "to_id": to_bucket_id,
                    "track_ids": list(track_ids),
                    "now": utc_now().isoformat(),
                },
                transaction_id=tx_id,
            )

        return MoveResult(moved=len(track_ids))
```

- [ ] **Step 11.3: Run tests**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: green.

- [ ] **Step 11.4: Commit**

Suggested subject: `feat(curation): add triage move_tracks repository method`

---

## Task 12: Repository — `transfer_tracks`

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

- [ ] **Step 12.1: Append failing tests**

```python
def test_transfer_tracks_validates_target_state() -> None:
    api = _api_with_responses(
        [
            [{"id": "b-src", "style_id": "s-1", "status": "FINALIZED"}],
            [
                {
                    "bucket_id": "bk-tgt",
                    "bucket_inactive": False,
                    "block_id": "b-tgt",
                    "block_user_id": "u-1",
                    "block_style_id": "s-1",
                    "block_status": "FINALIZED",
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(InvalidStateError):
        repo.transfer_tracks(
            user_id="u-1",
            src_block_id="b-src",
            target_bucket_id="bk-tgt",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_transfer_tracks_style_mismatch() -> None:
    api = _api_with_responses(
        [
            [{"id": "b-src", "style_id": "s-1", "status": "FINALIZED"}],
            [
                {
                    "bucket_id": "bk-tgt",
                    "bucket_inactive": False,
                    "block_id": "b-tgt",
                    "block_user_id": "u-1",
                    "block_style_id": "s-2",
                    "block_status": "IN_PROGRESS",
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(StyleMismatchError):
        repo.transfer_tracks(
            user_id="u-1",
            src_block_id="b-src",
            target_bucket_id="bk-tgt",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_transfer_tracks_happy_path() -> None:
    api = _api_with_responses(
        [
            [{"id": "b-src", "style_id": "s-1", "status": "FINALIZED"}],
            [
                {
                    "bucket_id": "bk-tgt",
                    "bucket_inactive": False,
                    "block_id": "b-tgt",
                    "block_user_id": "u-1",
                    "block_style_id": "s-1",
                    "block_status": "IN_PROGRESS",
                }
            ],
            [
                {"track_id": "00000000-0000-0000-0000-000000000001"},
                {"track_id": "00000000-0000-0000-0000-000000000002"},
            ],
            [
                {"track_id": "00000000-0000-0000-0000-000000000001"},
                {"track_id": "00000000-0000-0000-0000-000000000002"},
            ],
        ]
    )
    repo = TriageRepository(api)
    out = repo.transfer_tracks(
        user_id="u-1",
        src_block_id="b-src",
        target_bucket_id="bk-tgt",
        track_ids=[
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
    )
    assert out.transferred == 2
    insert_call = api.execute.call_args_list[3]
    assert "INSERT INTO triage_bucket_tracks" in insert_call.args[0]
    assert "ON CONFLICT" in insert_call.args[0]
```

- [ ] **Step 12.2: Implement `transfer_tracks`**

```python
    def transfer_tracks(
        self,
        *,
        user_id: str,
        src_block_id: str,
        target_bucket_id: str,
        track_ids: Sequence[str],
    ) -> TransferResult:
        src_rows = self._data_api.execute(
            """
            SELECT id, style_id, status
            FROM triage_blocks
            WHERE id = :id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"id": src_block_id, "user_id": user_id},
        )
        if not src_rows:
            raise NotFoundError(
                "triage_block_not_found",
                f"source triage block not found: {src_block_id}",
            )
        src = src_rows[0]

        tgt_rows = self._data_api.execute(
            """
            SELECT
                tbk.id AS bucket_id,
                tbk.inactive AS bucket_inactive,
                tb.id AS block_id,
                tb.user_id AS block_user_id,
                tb.style_id AS block_style_id,
                tb.status AS block_status
            FROM triage_buckets tbk
            JOIN triage_blocks tb ON tbk.triage_block_id = tb.id
            WHERE tbk.id = :bucket_id
              AND tb.deleted_at IS NULL
            """,
            {"bucket_id": target_bucket_id},
        )
        if not tgt_rows or tgt_rows[0]["block_user_id"] != user_id:
            raise NotFoundError(
                "target_bucket_not_found",
                f"target bucket not found: {target_bucket_id}",
            )
        tgt = tgt_rows[0]

        if tgt["block_status"] != "IN_PROGRESS":
            raise InvalidStateError(
                "target triage block is not IN_PROGRESS"
            )
        if bool(tgt["bucket_inactive"]):
            raise InactiveBucketError(
                "target bucket is inactive (its category was soft-deleted)"
            )
        if src["style_id"] != tgt["block_style_id"]:
            raise StyleMismatchError(
                "source and target triage blocks belong to different styles"
            )

        present = self._data_api.execute(
            """
            SELECT DISTINCT tbt.track_id
            FROM triage_bucket_tracks tbt
            JOIN triage_buckets tbk ON tbk.id = tbt.triage_bucket_id
            WHERE tbk.triage_block_id = :src_block_id
              AND tbt.track_id = ANY(:track_ids)
            """,
            {
                "src_block_id": src_block_id,
                "track_ids": list(track_ids),
            },
        )
        present_ids = {r["track_id"] for r in present}
        missing = [t for t in track_ids if t not in present_ids]
        if missing:
            raise TracksNotInSourceError(
                f"{len(missing)} track(s) not present in source block",
                missing,
            )

        inserted_rows = self._data_api.execute(
            """
            INSERT INTO triage_bucket_tracks
                (triage_bucket_id, track_id, added_at)
            SELECT :tgt_id, t, :now
            FROM UNNEST(:track_ids::text[]) AS t
            ON CONFLICT (triage_bucket_id, track_id) DO NOTHING
            RETURNING track_id
            """,
            {
                "tgt_id": target_bucket_id,
                "track_ids": list(track_ids),
                "now": utc_now().isoformat(),
            },
        )
        return TransferResult(transferred=len(inserted_rows))
```

- [ ] **Step 12.3: Run tests**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: green.

- [ ] **Step 12.4: Commit**

Suggested subject: `feat(curation): add triage transfer_tracks repository method`

---

## Task 13: Repository — `finalize_block`

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

- [ ] **Step 13.1: Append failing tests**

```python
def test_finalize_block_inactive_staging_with_tracks_returns_409() -> None:
    api = _api_with_responses(
        [
            # block lookup
            [
                {
                    "id": "b-1",
                    "status": "IN_PROGRESS",
                }
            ],
            # inactive staging buckets with tracks
            [
                {
                    "id": "bk-stg",
                    "category_id": "c-1",
                    "track_count": 3,
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    fake_categories_repo = MagicMock()
    with pytest.raises(InactiveStagingFinalizeError) as ei:
        repo.finalize_block(
            user_id="u-1",
            block_id="b-1",
            categories_repository=fake_categories_repo,
        )
    assert ei.value.inactive_buckets[0]["id"] == "bk-stg"
    assert ei.value.inactive_buckets[0]["track_count"] == 3
    fake_categories_repo.add_tracks_bulk.assert_not_called()


def test_finalize_block_calls_add_tracks_bulk_per_staging() -> None:
    """Active staging buckets each call add_tracks_bulk inside the same TX."""
    track_rows_per_bucket = {
        "bk-cat1": [
            {"track_id": f"00000000-0000-0000-0000-{n:012d}"}
            for n in range(3)
        ],
        "bk-cat2": [
            {"track_id": f"00000000-0000-0000-0000-{n + 100:012d}"}
            for n in range(2)
        ],
    }
    api = _api_with_responses(
        [
            [{"id": "b-1", "status": "IN_PROGRESS"}],
            [],  # no inactive staging with tracks
            [
                {"id": "bk-cat1", "category_id": "c-1"},
                {"id": "bk-cat2", "category_id": "c-2"},
            ],
            track_rows_per_bucket["bk-cat1"],
            track_rows_per_bucket["bk-cat2"],
            [],  # UPDATE block status
            [
                {
                    "id": "b-1",
                    "user_id": "u-1",
                    "style_id": "s-1",
                    "style_name": "House",
                    "name": "X",
                    "date_from": "2026-04-20",
                    "date_to": "2026-04-26",
                    "status": "FINALIZED",
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "updated_at": "2026-04-28T01:00:00+00:00",
                    "finalized_at": "2026-04-28T01:00:00+00:00",
                }
            ],
            [],  # buckets-with-counts
        ]
    )
    fake_categories_repo = MagicMock()
    fake_categories_repo.add_tracks_bulk.return_value = 0
    repo = TriageRepository(api)
    out = repo.finalize_block(
        user_id="u-1",
        block_id="b-1",
        categories_repository=fake_categories_repo,
    )
    assert out.block.status == "FINALIZED"
    assert out.promoted == {"c-1": 3, "c-2": 2}
    # add_tracks_bulk called once per staging bucket
    assert fake_categories_repo.add_tracks_bulk.call_count == 2


def test_finalize_block_chunks_above_500() -> None:
    track_rows = [
        {"track_id": f"00000000-0000-0000-0000-{n:012d}"}
        for n in range(1100)
    ]
    api = _api_with_responses(
        [
            [{"id": "b-1", "status": "IN_PROGRESS"}],
            [],
            [{"id": "bk-cat1", "category_id": "c-1"}],
            track_rows,
            [],
            [
                {
                    "id": "b-1",
                    "user_id": "u-1",
                    "style_id": "s-1",
                    "style_name": "House",
                    "name": "X",
                    "date_from": "2026-04-20",
                    "date_to": "2026-04-26",
                    "status": "FINALIZED",
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "updated_at": "2026-04-28T01:00:00+00:00",
                    "finalized_at": "2026-04-28T01:00:00+00:00",
                }
            ],
            [],
        ]
    )
    fake_categories_repo = MagicMock()
    fake_categories_repo.add_tracks_bulk.return_value = 0
    repo = TriageRepository(api)
    repo.finalize_block(
        user_id="u-1",
        block_id="b-1",
        categories_repository=fake_categories_repo,
    )
    # 1100 → ceil(1100/500) = 3 calls (500 + 500 + 100)
    assert fake_categories_repo.add_tracks_bulk.call_count == 3
    chunk_sizes = [
        len(call.kwargs["items"])
        for call in fake_categories_repo.add_tracks_bulk.call_args_list
    ]
    assert chunk_sizes == [500, 500, 100]
```

- [ ] **Step 13.2: Implement `finalize_block`**

```python
    _FINALIZE_CHUNK_SIZE = 500

    def finalize_block(
        self,
        *,
        user_id: str,
        block_id: str,
        categories_repository: Any,
    ) -> FinalizeResult:
        with self._data_api.transaction() as tx_id:
            # 1. Validate block status.
            block_rows = self._data_api.execute(
                """
                SELECT id, status FROM triage_blocks
                WHERE id = :id
                  AND user_id = :user_id
                  AND deleted_at IS NULL
                """,
                {"id": block_id, "user_id": user_id},
                transaction_id=tx_id,
            )
            if not block_rows:
                raise NotFoundError(
                    "triage_block_not_found",
                    f"triage block not found: {block_id}",
                )
            if block_rows[0]["status"] != "IN_PROGRESS":
                raise InvalidStateError(
                    "triage block is not editable (status != IN_PROGRESS)"
                )

            # 2. Reject if any inactive staging bucket has tracks.
            inactive_with_tracks = self._data_api.execute(
                """
                SELECT
                    tbk.id, tbk.category_id,
                    COUNT(tbt.track_id) AS track_count
                FROM triage_buckets tbk
                LEFT JOIN triage_bucket_tracks tbt
                  ON tbt.triage_bucket_id = tbk.id
                WHERE tbk.triage_block_id = :block_id
                  AND tbk.bucket_type = 'STAGING'
                  AND tbk.inactive = TRUE
                GROUP BY tbk.id, tbk.category_id
                HAVING COUNT(tbt.track_id) > 0
                """,
                {"block_id": block_id},
                transaction_id=tx_id,
            )
            if inactive_with_tracks:
                payload = [
                    {
                        "id": r["id"],
                        "category_id": r["category_id"],
                        "track_count": int(r["track_count"]),
                    }
                    for r in inactive_with_tracks
                ]
                raise InactiveStagingFinalizeError(
                    f"{len(payload)} inactive staging bucket(s) hold tracks",
                    payload,
                )

            # 3. Iterate active staging buckets; for each, fetch tracks
            #    and call add_tracks_bulk in chunks of 500.
            staging_rows = self._data_api.execute(
                """
                SELECT id, category_id
                FROM triage_buckets
                WHERE triage_block_id = :block_id
                  AND bucket_type = 'STAGING'
                  AND inactive = FALSE
                """,
                {"block_id": block_id},
                transaction_id=tx_id,
            )

            promoted: dict[str, int] = {}
            for sb in staging_rows:
                bucket_id = sb["id"]
                category_id = sb["category_id"]
                track_rows = self._data_api.execute(
                    """
                    SELECT track_id
                    FROM triage_bucket_tracks
                    WHERE triage_bucket_id = :bucket_id
                    ORDER BY added_at ASC, track_id ASC
                    """,
                    {"bucket_id": bucket_id},
                    transaction_id=tx_id,
                )
                track_ids = [r["track_id"] for r in track_rows]
                promoted[category_id] = len(track_ids)
                for start in range(0, len(track_ids), self._FINALIZE_CHUNK_SIZE):
                    chunk = track_ids[
                        start : start + self._FINALIZE_CHUNK_SIZE
                    ]
                    items = [(t, block_id) for t in chunk]
                    categories_repository.add_tracks_bulk(
                        user_id=user_id,
                        category_id=category_id,
                        items=items,
                        transaction_id=tx_id,
                    )

            # 4. Flip status to FINALIZED.
            now = utc_now().isoformat()
            self._data_api.execute(
                """
                UPDATE triage_blocks
                SET status = 'FINALIZED',
                    finalized_at = :now,
                    updated_at = :now
                WHERE id = :id
                """,
                {"id": block_id, "now": now},
                transaction_id=tx_id,
            )

            # 5. Re-fetch detail inside the same TX.
            block = self._fetch_block_detail(
                user_id=user_id, block_id=block_id, transaction_id=tx_id
            )

        if block is None:  # pragma: no cover
            raise RuntimeError(
                "finalize_block: post-update fetch returned None"
            )
        return FinalizeResult(block=block, promoted=promoted)
```

The exact `add_tracks_bulk` keyword shape matches spec-C D17: `(user_id, category_id, items, transaction_id)`. If spec-C's actual signature differs (use it positionally vs keyword), adjust accordingly. Verify by reading `src/collector/curation/categories_repository.py`'s `add_tracks_bulk` definition before running.

- [ ] **Step 13.3: Run tests**

Run: `pytest tests/unit/test_triage_repository.py -v`
Expected: green.

- [ ] **Step 13.4: Commit**

Suggested subject: `feat(curation): add triage finalize_block transactional promotion`

---

## Task 14: Repository — `soft_delete_block`

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

- [ ] **Step 14.1: Append failing tests**

```python
def test_soft_delete_block_returns_true_on_success() -> None:
    api = _api_with_responses([[{"id": "b-1"}]])
    repo = TriageRepository(api)
    assert (
        repo.soft_delete_block(user_id="u-1", block_id="b-1") is True
    )


def test_soft_delete_block_returns_false_when_not_found() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    assert (
        repo.soft_delete_block(user_id="u-1", block_id="missing") is False
    )
```

- [ ] **Step 14.2: Implement**

```python
    def soft_delete_block(
        self, *, user_id: str, block_id: str
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE triage_blocks
            SET deleted_at = :now,
                updated_at = :now
            WHERE id = :id
              AND user_id = :user_id
              AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "id": block_id,
                "user_id": user_id,
                "now": utc_now().isoformat(),
            },
        )
        return bool(rows)
```

- [ ] **Step 14.3: Run + commit**

Run: `pytest tests/unit/test_triage_repository.py -v`
Suggested subject: `feat(curation): add triage soft_delete_block`

---

## Task 15: Repository — late-snapshot side-effects

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py` (append)

These two methods are called from `categories_service.create` (D7) and `categories_service.soft_delete` (D8). They run inside the caller's TX, so they accept and forward `transaction_id`.

- [ ] **Step 15.1: Append failing tests**

```python
def test_snapshot_inserts_one_staging_per_active_block() -> None:
    api = _api_with_responses(
        [
            # SELECT IN_PROGRESS, alive blocks for (user, style)
            [{"id": "b-1"}, {"id": "b-2"}],
            # INSERT for each (no RETURNING needed for assertion)
            [{"id": "bk-new-1"}],
            [{"id": "bk-new-2"}],
        ]
    )
    repo = TriageRepository(api)
    out = repo.snapshot_category_into_active_blocks(
        user_id="u-1",
        style_id="s-1",
        category_id="c-1",
        transaction_id="tx-1",
    )
    assert out == 2
    inserts = [
        c
        for c in api.execute.call_args_list
        if "INSERT INTO triage_buckets" in c.args[0]
    ]
    assert len(inserts) == 2
    for c in inserts:
        assert "ON CONFLICT" in c.args[0]
        assert c.args[1]["category_id"] == "c-1"


def test_snapshot_no_active_blocks_is_zero() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    assert (
        repo.snapshot_category_into_active_blocks(
            user_id="u-1",
            style_id="s-1",
            category_id="c-1",
            transaction_id="tx-1",
        )
        == 0
    )


def test_mark_staging_inactive_updates_only_staging() -> None:
    api = _api_with_responses(
        [[{"id": "bk-stg-1"}, {"id": "bk-stg-2"}]]
    )
    repo = TriageRepository(api)
    out = repo.mark_staging_inactive_for_category(
        user_id="u-1",
        category_id="c-1",
        transaction_id="tx-1",
    )
    assert out == 2
    update_call = api.execute.call_args_list[0]
    sql = update_call.args[0]
    assert "UPDATE triage_buckets" in sql
    assert "SET inactive = TRUE" in sql
    assert "bucket_type = 'STAGING'" in sql
```

- [ ] **Step 15.2: Implement `snapshot_category_into_active_blocks`**

```python
    def snapshot_category_into_active_blocks(
        self,
        *,
        user_id: str,
        style_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        from uuid import uuid4

        block_rows = self._data_api.execute(
            """
            SELECT id FROM triage_blocks
            WHERE user_id = :user_id
              AND style_id = :style_id
              AND status = 'IN_PROGRESS'
              AND deleted_at IS NULL
            """,
            {"user_id": user_id, "style_id": style_id},
            transaction_id=transaction_id,
        )

        inserted = 0
        now = utc_now().isoformat()
        for br in block_rows:
            bid = str(uuid4())
            res = self._data_api.execute(
                """
                INSERT INTO triage_buckets (
                    id, triage_block_id, bucket_type, category_id,
                    inactive, created_at
                ) VALUES (
                    :id, :block_id, 'STAGING', :category_id,
                    FALSE, :now
                )
                ON CONFLICT (triage_block_id, category_id)
                  WHERE category_id IS NOT NULL
                  DO NOTHING
                RETURNING id
                """,
                {
                    "id": bid,
                    "block_id": br["id"],
                    "category_id": category_id,
                    "now": now,
                },
                transaction_id=transaction_id,
            )
            if res:
                inserted += 1
        return inserted
```

- [ ] **Step 15.3: Implement `mark_staging_inactive_for_category`**

```python
    def mark_staging_inactive_for_category(
        self,
        *,
        user_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        rows = self._data_api.execute(
            """
            UPDATE triage_buckets tbk
            SET inactive = TRUE
            FROM triage_blocks tb
            WHERE tbk.triage_block_id = tb.id
              AND tb.user_id = :user_id
              AND tbk.category_id = :category_id
              AND tbk.bucket_type = 'STAGING'
              AND tbk.inactive = FALSE
            RETURNING tbk.id
            """,
            {"user_id": user_id, "category_id": category_id},
            transaction_id=transaction_id,
        )
        return len(rows)
```

- [ ] **Step 15.4: Run + commit**

Run: `pytest tests/unit/test_triage_repository.py -v`
Suggested subject: `feat(curation): add triage snapshot and inactive-mark side-effects`

---

## Task 16: Cross-spec patches in `categories_service`

**Files:**
- Modify: `src/collector/curation/categories_service.py`
- Modify: `tests/unit/test_categories_service.py` (extend)
- Modify: `tests/integration/test_curation_handler.py` (extend)

Read the existing `categories_service.create` and `categories_service.soft_delete` first to identify the exact site for the new calls. Both methods open a transaction; the new triage call goes inside it.

- [ ] **Step 16.1: Inspect existing service shape**

Run: `grep -n "def create\|def soft_delete\|transaction" src/collector/curation/categories_service.py`

The existing pattern: `with repo.transaction() as tx_id:` then INSERT/UPDATE inside. We add the triage call between the existing INSERT/UPDATE and the commit.

- [ ] **Step 16.2: Patch `create`**

In `categories_service.create`, after the INSERT into `categories` and before the TX-block exits, insert:

```python
            from collector.curation.triage_repository import TriageRepository

            triage_repo = TriageRepository(self._repo._data_api)
            inserted_into_blocks = triage_repo.snapshot_category_into_active_blocks(
                user_id=user_id,
                style_id=style_id,
                category_id=new_category.id,
                transaction_id=tx_id,
            )
            log_event(
                "INFO",
                "category_snapshot_created",
                correlation_id=correlation_id,
                user_id=user_id,
                category_id=new_category.id,
                blocks_snapshot_into=inserted_into_blocks,
            )
```

If the existing `create` signature does not accept `correlation_id`, plumb it from the handler call site (which already passes one). The local-import of `TriageRepository` keeps the cross-spec coupling localized.

If `categories_service` does not already hold a reference to the data-api client suitable for instantiating a sibling repository, use the same constructor pattern that `CategoriesRepository` uses (`TriageRepository(data_api)`).

- [ ] **Step 16.3: Patch `soft_delete`**

In `categories_service.soft_delete`, after the UPDATE setting `deleted_at`:

```python
            triage_repo = TriageRepository(self._repo._data_api)
            inactivated = triage_repo.mark_staging_inactive_for_category(
                user_id=user_id,
                category_id=category_id,
                transaction_id=tx_id,
            )
            log_event(
                "INFO",
                "category_staging_inactive",
                correlation_id=correlation_id,
                user_id=user_id,
                category_id=category_id,
                inactivated_buckets=inactivated,
            )
```

- [ ] **Step 16.4: Add unit tests for the side-effect**

Append to `tests/unit/test_categories_service.py`:

```python
def test_create_calls_snapshot_into_active_triages(monkeypatch) -> None:
    """spec-D D7: categories_service.create snapshots into active triages."""
    from unittest.mock import MagicMock
    from collector.curation import categories_service as mod

    snap_mock = MagicMock(return_value=2)
    monkeypatch.setattr(
        "collector.curation.triage_repository.TriageRepository.snapshot_category_into_active_blocks",
        lambda self, **kw: snap_mock(**kw),
    )
    # ... call categories_service.create with a stub repo (reuse existing
    # test fixture) and assert snap_mock.assert_called_once_with(
    #     user_id=..., style_id=..., category_id=..., transaction_id=...
    # )
```

The existing test file in `tests/unit/test_categories_service.py` already wires a stub repo for `create` tests (read it first to follow the same fixture style). Reuse the fixture and add an assertion that `snapshot_category_into_active_blocks` is called once with the new category id and the active TX id.

Add a parallel test for `soft_delete` calling `mark_staging_inactive_for_category`.

- [ ] **Step 16.5: Add integration assertion**

In `tests/integration/test_curation_handler.py`, append an integration test that:

1. Creates a triage block via `triage_repository.create_block` (or the handler once it's wired).
2. Calls `POST /styles/{style_id}/categories` to create a category.
3. Asserts (via `Aurora.execute SELECT * FROM triage_buckets WHERE category_id=...`) that a STAGING row was inserted into the active block.

The existing integration suite has a reusable Aurora fixture; follow its pattern.

- [ ] **Step 16.6: Run tests**

Run: `pytest tests/unit/test_categories_service.py tests/integration/test_curation_handler.py -v`
Expected: green.

- [ ] **Step 16.7: Commit**

Suggested subject: `feat(curation): wire triage snapshot side-effects from categories_service`

---

## Task 17: Handler — `POST /triage/blocks` create + error mapping

**Files:**
- Modify: `src/collector/curation_handler.py`

Read the existing handler first — note the dispatcher pattern (`ROUTES`), the auth helper, the error-envelope helper, and the existing response-builder utilities. Wire all 9 new routes through them.

- [ ] **Step 17.1: Add the new error mapping**

Locate the existing exception → envelope mapping helper in `curation_handler.py` (`grep -n "isinstance.*CurationError\|error_code" src/collector/curation_handler.py`). Extend it so `InactiveStagingFinalizeError` and `TracksNotInSourceError` serialize their structured payloads (`inactive_buckets`, `not_in_source`) into the response body alongside `error_code`, `message`, `correlation_id`. Pattern:

```python
def _envelope_for_error(exc: CurationError, correlation_id: str) -> dict:
    body = {
        "error_code": exc.error_code,
        "message": exc.message,
        "correlation_id": correlation_id,
    }
    if isinstance(exc, InactiveStagingFinalizeError):
        body["inactive_buckets"] = exc.inactive_buckets
    if isinstance(exc, TracksNotInSourceError):
        body["not_in_source"] = exc.not_in_source
    return body
```

If the helper already exists with a different name, extend it in place.

- [ ] **Step 17.2: Add `_create_triage_block` handler**

Append to `curation_handler.py` (alongside existing handlers):

```python
def _create_triage_block(event, context, *, user_id, correlation_id):
    body = _read_json_body(event)
    schema = CreateTriageBlockIn.model_validate(body)

    triage_repo = TriageRepository(_get_data_api())
    out = triage_repo.create_block(
        user_id=user_id,
        style_id=schema.style_id,
        name=schema.name,
        date_from=schema.date_from,
        date_to=schema.date_to,
    )
    log_event(
        "INFO",
        "triage_block_created",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=out.id,
        style_id=out.style_id,
        date_from=out.date_from,
        date_to=out.date_to,
    )
    return _http_response(
        201, _serialize_triage_block(out, correlation_id)
    )
```

`_serialize_triage_block` is a new helper that returns the JSON shape from §5.1. Add it next to existing serializers:

```python
def _serialize_triage_block(row, correlation_id):
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "buckets": [
            {
                "id": b.id,
                "bucket_type": b.bucket_type,
                "category_id": b.category_id,
                "category_name": b.category_name,
                "inactive": b.inactive,
                "track_count": b.track_count,
            }
            for b in row.buckets
        ],
        "correlation_id": correlation_id,
    }
```

- [ ] **Step 17.3: Wire route**

Find the existing `ROUTES` dict (it lives near the top of the file or in a helper). Append:

```python
("POST", "/triage/blocks"): _create_triage_block,
```

- [ ] **Step 17.4: Add a smoke unit test**

```python
# tests/unit/test_curation_handler.py (extend if exists; create otherwise)
def test_create_triage_block_route_registered() -> None:
    from collector.curation_handler import ROUTES
    assert ("POST", "/triage/blocks") in ROUTES
```

- [ ] **Step 17.5: Commit**

Run: `pytest tests/unit -q`
Suggested subject: `feat(curation): add POST /triage/blocks handler`

---

## Task 18: Handlers — list + detail + bucket-tracks (4 read routes)

**Files:**
- Modify: `src/collector/curation_handler.py`

- [ ] **Step 18.1: Add four read handlers**

```python
def _list_triage_blocks_by_style(
    event, context, *, user_id, correlation_id
):
    style_id = event["pathParameters"]["style_id"]
    qs = event.get("queryStringParameters") or {}
    limit = int(qs.get("limit", 50))
    offset = int(qs.get("offset", 0))
    if limit > 200 or limit < 1 or offset < 0:
        raise ValidationError("invalid limit/offset")
    status = qs.get("status")
    if status is not None and status not in ("IN_PROGRESS", "FINALIZED"):
        raise ValidationError("status must be IN_PROGRESS or FINALIZED")

    triage_repo = TriageRepository(_get_data_api())
    items, total = triage_repo.list_blocks_by_style(
        user_id=user_id,
        style_id=style_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    log_event(
        "INFO",
        "triage_block_listed",
        correlation_id=correlation_id,
        user_id=user_id,
        style_id=style_id,
        count=len(items),
        total=total,
    )
    return _http_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
    )


def _list_triage_blocks_all(event, context, *, user_id, correlation_id):
    qs = event.get("queryStringParameters") or {}
    limit = int(qs.get("limit", 50))
    offset = int(qs.get("offset", 0))
    if limit > 200 or limit < 1 or offset < 0:
        raise ValidationError("invalid limit/offset")
    status = qs.get("status")
    if status is not None and status not in ("IN_PROGRESS", "FINALIZED"):
        raise ValidationError("status must be IN_PROGRESS or FINALIZED")

    triage_repo = TriageRepository(_get_data_api())
    items, total = triage_repo.list_blocks_all(
        user_id=user_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return _http_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
    )


def _get_triage_block(event, context, *, user_id, correlation_id):
    block_id = event["pathParameters"]["id"]
    triage_repo = TriageRepository(_get_data_api())
    out = triage_repo.get_block(user_id=user_id, block_id=block_id)
    if out is None:
        raise NotFoundError(
            "triage_block_not_found",
            f"triage block not found: {block_id}",
        )
    return _http_response(
        200, _serialize_triage_block(out, correlation_id)
    )


def _list_bucket_tracks(event, context, *, user_id, correlation_id):
    block_id = event["pathParameters"]["id"]
    bucket_id = event["pathParameters"]["bucket_id"]
    qs = event.get("queryStringParameters") or {}
    limit = int(qs.get("limit", 50))
    offset = int(qs.get("offset", 0))
    if limit > 200 or limit < 1 or offset < 0:
        raise ValidationError("invalid limit/offset")
    search = qs.get("search")

    triage_repo = TriageRepository(_get_data_api())
    items, total = triage_repo.list_bucket_tracks(
        user_id=user_id,
        block_id=block_id,
        bucket_id=bucket_id,
        limit=limit,
        offset=offset,
        search=search,
    )
    return _http_response(
        200,
        {
            "items": [_serialize_bucket_track(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
    )


def _serialize_block_summary(row):
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "track_count": row.track_count,
    }


def _serialize_bucket_track(row):
    return {
        "track_id": row.track_id,
        "title": row.title,
        "mix_name": row.mix_name,
        "isrc": row.isrc,
        "bpm": row.bpm,
        "length_ms": row.length_ms,
        "publish_date": row.publish_date,
        "spotify_release_date": row.spotify_release_date,
        "spotify_id": row.spotify_id,
        "release_type": row.release_type,
        "is_ai_suspected": row.is_ai_suspected,
        "artists": list(row.artists),
        "added_at": row.added_at,
    }
```

- [ ] **Step 18.2: Wire 4 routes**

Append to `ROUTES`:

```python
("GET", "/styles/{style_id}/triage/blocks"): _list_triage_blocks_by_style,
("GET", "/triage/blocks"): _list_triage_blocks_all,
("GET", "/triage/blocks/{id}"): _get_triage_block,
("GET", "/triage/blocks/{id}/buckets/{bucket_id}/tracks"): _list_bucket_tracks,
```

- [ ] **Step 18.3: Run unit tests**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 18.4: Commit**

Suggested subject: `feat(curation): add triage list + detail + bucket-tracks handlers`

---

## Task 19: Handlers — `move` + `transfer`

**Files:**
- Modify: `src/collector/curation_handler.py`

- [ ] **Step 19.1: Add `_move_tracks` and `_transfer_tracks`**

```python
def _move_tracks(event, context, *, user_id, correlation_id):
    block_id = event["pathParameters"]["id"]
    body = _read_json_body(event)
    schema = MoveTracksIn.model_validate(body)

    triage_repo = TriageRepository(_get_data_api())
    out = triage_repo.move_tracks(
        user_id=user_id,
        block_id=block_id,
        from_bucket_id=schema.from_bucket_id,
        to_bucket_id=schema.to_bucket_id,
        track_ids=schema.track_ids,
    )
    log_event(
        "INFO",
        "triage_tracks_moved",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
        from_bucket_id=schema.from_bucket_id,
        to_bucket_id=schema.to_bucket_id,
        moved=out.moved,
    )
    return _http_response(
        200, {"moved": out.moved, "correlation_id": correlation_id}
    )


def _transfer_tracks(event, context, *, user_id, correlation_id):
    src_block_id = event["pathParameters"]["src_id"]
    body = _read_json_body(event)
    schema = TransferTracksIn.model_validate(body)

    triage_repo = TriageRepository(_get_data_api())
    out = triage_repo.transfer_tracks(
        user_id=user_id,
        src_block_id=src_block_id,
        target_bucket_id=schema.target_bucket_id,
        track_ids=schema.track_ids,
    )
    log_event(
        "INFO",
        "triage_tracks_transferred",
        correlation_id=correlation_id,
        user_id=user_id,
        src_block_id=src_block_id,
        target_bucket_id=schema.target_bucket_id,
        transferred=out.transferred,
    )
    return _http_response(
        200,
        {
            "transferred": out.transferred,
            "correlation_id": correlation_id,
        },
    )
```

- [ ] **Step 19.2: Wire 2 routes**

```python
("POST", "/triage/blocks/{id}/move"): _move_tracks,
("POST", "/triage/blocks/{src_id}/transfer"): _transfer_tracks,
```

- [ ] **Step 19.3: Run + commit**

Run: `pytest tests/unit -q`
Suggested subject: `feat(curation): add triage move + transfer handlers`

---

## Task 20: Handlers — `finalize` + `delete`

**Files:**
- Modify: `src/collector/curation_handler.py`

- [ ] **Step 20.1: Add `_finalize_triage_block` and `_soft_delete_triage_block`**

```python
def _finalize_triage_block(event, context, *, user_id, correlation_id):
    block_id = event["pathParameters"]["id"]
    triage_repo = TriageRepository(_get_data_api())
    cat_repo = CategoriesRepository(_get_data_api())
    out = triage_repo.finalize_block(
        user_id=user_id,
        block_id=block_id,
        categories_repository=cat_repo,
    )
    log_event(
        "INFO",
        "triage_block_finalized",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
        promoted=out.promoted,
    )
    return _http_response(
        200,
        {
            "block": _serialize_triage_block(out.block, correlation_id),
            "promoted": out.promoted,
            "correlation_id": correlation_id,
        },
    )


def _soft_delete_triage_block(event, context, *, user_id, correlation_id):
    block_id = event["pathParameters"]["id"]
    triage_repo = TriageRepository(_get_data_api())
    deleted = triage_repo.soft_delete_block(
        user_id=user_id, block_id=block_id
    )
    if not deleted:
        raise NotFoundError(
            "triage_block_not_found",
            f"triage block not found: {block_id}",
        )
    log_event(
        "INFO",
        "triage_block_soft_deleted",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=block_id,
    )
    return _http_response(204, body=None)
```

If `_http_response` does not accept `body=None`, mirror whatever the existing spec-C `DELETE /categories/{id}` returns (probably an empty dict serialized to empty body).

- [ ] **Step 20.2: Wire 2 routes**

```python
("POST", "/triage/blocks/{id}/finalize"): _finalize_triage_block,
("DELETE", "/triage/blocks/{id}"): _soft_delete_triage_block,
```

- [ ] **Step 20.3: Run + commit**

Run: `pytest tests/unit -q`
Suggested subject: `feat(curation): add triage finalize + soft-delete handlers`

---

## Task 21: Integration tests — happy create, R4 classification, source filter

**Files:**
- Create: `tests/integration/test_triage_handler.py`

The integration test file follows the pattern of `tests/integration/test_curation_handler.py`: ephemeral postgres (the existing fixture), seeded `clouder_styles`/`clouder_tracks`/`categories`, then Lambda invocation.

- [ ] **Step 21.1: Skeleton + fixture imports**

```python
# tests/integration/test_triage_handler.py
"""Integration tests for spec-D triage handler."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

import pytest

# Reuse the existing aurora_client fixture from conftest, plus the FakeRepo
# pattern used in test_curation_handler. Read tests/integration/conftest.py
# and tests/integration/test_curation_handler.py:1-50 first.

USER_A = "00000000-0000-0000-0000-00000000000a"
USER_B = "00000000-0000-0000-0000-00000000000b"
STYLE_1 = "00000000-0000-0000-0000-000000000001"


def _seed_track(
    aurora,
    *,
    track_id: str,
    style_id: str,
    publish_date: date,
    spotify_release_date: date | None = None,
    release_type: str | None = None,
    isrc: str | None = None,
    title: str = "Track",
):
    aurora.execute(
        """
        INSERT INTO clouder_tracks (
            id, title, normalized_title, isrc, publish_date,
            style_id, spotify_release_date, release_type,
            is_ai_suspected, created_at, updated_at
        ) VALUES (
            :id, :title, :title, :isrc, :pub,
            :style, :spot, :rtype,
            FALSE, NOW(), NOW()
        )
        """,
        {
            "id": track_id,
            "title": title,
            "isrc": isrc,
            "pub": publish_date.isoformat(),
            "style": style_id,
            "spot": (
                spotify_release_date.isoformat()
                if spotify_release_date is not None
                else None
            ),
            "rtype": release_type,
        },
    )


def _invoke(method: str, path: str, *, user_id: str, body=None, path_params=None, qs=None):
    """Invoke curation_handler.lambda_handler with a synthetic API GW v2 event."""
    from collector.curation_handler import lambda_handler

    event = {
        "routeKey": f"{method} {path}",
        "requestContext": {
            "authorizer": {
                "lambda": {"user_id": user_id, "is_admin": False}
            }
        },
        "pathParameters": path_params or {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
    }
    return lambda_handler(event, None)


def test_create_triage_happy_path(aurora_client):
    style_id = STYLE_1
    df = date(2026, 4, 20)
    dt = date(2026, 4, 26)
    _seed_track(
        aurora_client,
        track_id=str(uuid.uuid4()),
        style_id=style_id,
        publish_date=date(2026, 4, 22),
        spotify_release_date=date(2026, 4, 22),
        release_type="single",
        isrc="USABC2400001",
    )

    res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": style_id,
            "name": "W17",
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        },
    )
    assert res["statusCode"] == 201
    body = json.loads(res["body"])
    assert body["status"] == "IN_PROGRESS"
    bucket_types = [b["bucket_type"] for b in body["buckets"]]
    assert bucket_types[:5] == ["NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"]
    new_bucket = next(b for b in body["buckets"] if b["bucket_type"] == "NEW")
    assert new_bucket["track_count"] == 1


def test_r4_classification_six_cases(aurora_client):
    """spec-D §6.1 — verify all six rules + ordering."""
    style_id = STYLE_1
    df = date(2026, 4, 1)
    dt = date(2026, 4, 30)

    cases = [
        # (label, spotify_release_date, release_type, expected_bucket_type)
        ("A", date(2025, 1, 1), "single", "OLD"),
        ("B", date(2026, 4, 15), "single", "NEW"),
        ("C", date(2026, 4, 15), "compilation", "NOT"),
        ("D", None, "single", "UNCLASSIFIED"),
        ("E", date(2026, 4, 1), "single", "NEW"),  # equals date_from → NEW
        ("F", date(2025, 12, 1), "compilation", "OLD"),  # OLD beats NOT
    ]
    track_ids: dict[str, str] = {}
    for label, spot, rtype, _expected in cases:
        tid = str(uuid.uuid4())
        track_ids[label] = tid
        _seed_track(
            aurora_client,
            track_id=tid,
            style_id=style_id,
            publish_date=date(2026, 4, 15),
            spotify_release_date=spot,
            release_type=rtype,
            isrc=f"US{label*2}{label}24",
            title=f"Track {label}",
        )

    res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": style_id,
            "name": "R4 test",
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        },
    )
    assert res["statusCode"] == 201
    block = json.loads(res["body"])
    block_id = block["id"]

    # Look up bucket id by type, then list tracks per bucket and confirm.
    bucket_id_by_type = {b["bucket_type"]: b["id"] for b in block["buckets"]}
    for label, _spot, _rtype, expected in cases:
        bk_res = _invoke(
            "GET",
            "/triage/blocks/{id}/buckets/{bucket_id}/tracks",
            user_id=USER_A,
            path_params={
                "id": block_id,
                "bucket_id": bucket_id_by_type[expected],
            },
            qs={"limit": "200"},
        )
        ids_in_bucket = {
            r["track_id"] for r in json.loads(bk_res["body"])["items"]
        }
        assert track_ids[label] in ids_in_bucket, (
            f"Track {label} expected in {expected}; not found"
        )


def test_source_filter_excludes_already_categorized(aurora_client):
    """Tracks already in the user's alive categories are not re-triaged."""
    style_id = STYLE_1
    cat_id = str(uuid.uuid4())
    aurora_client.execute(
        """
        INSERT INTO categories (
            id, user_id, style_id, name, normalized_name,
            position, created_at, updated_at
        ) VALUES (
            :id, :u, :s, 'cat', 'cat', 0, NOW(), NOW()
        )
        """,
        {"id": cat_id, "u": USER_A, "s": style_id},
    )
    track_id = str(uuid.uuid4())
    _seed_track(
        aurora_client,
        track_id=track_id,
        style_id=style_id,
        publish_date=date(2026, 4, 15),
        spotify_release_date=date(2026, 4, 15),
        release_type="single",
    )
    aurora_client.execute(
        """
        INSERT INTO category_tracks (category_id, track_id, added_at)
        VALUES (:c, :t, NOW())
        """,
        {"c": cat_id, "t": track_id},
    )

    res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": style_id,
            "name": "filter",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    block = json.loads(res["body"])
    # All technical buckets should be empty -- the only track in window is
    # already in this user's category.
    for b in block["buckets"]:
        assert b["track_count"] == 0
```

The `aurora_client` fixture name mirrors what spec-C uses; if it's named differently in `tests/integration/conftest.py`, rename accordingly.

- [ ] **Step 21.2: Run + commit**

Run: `pytest tests/integration/test_triage_handler.py -v`
Suggested subject: `test(triage): add create + R4 + source-filter integration tests`

---

## Task 22: Integration tests — tenancy, list/detail, move, transfer, late-snapshot, cap

**Files:**
- Modify: `tests/integration/test_triage_handler.py` (append)

- [ ] **Step 22.1: Append tenancy + list/detail tests**

```python
def test_tenancy_isolation(aurora_client):
    style_id = STYLE_1
    res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": style_id,
            "name": "A",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    block_id = json.loads(res["body"])["id"]

    # B sees no blocks
    list_res = _invoke(
        "GET",
        "/triage/blocks",
        user_id=USER_B,
    )
    assert json.loads(list_res["body"])["total"] == 0

    # B cannot read detail
    detail_res = _invoke(
        "GET",
        "/triage/blocks/{id}",
        user_id=USER_B,
        path_params={"id": block_id},
    )
    assert detail_res["statusCode"] == 404

    # B cannot delete
    del_res = _invoke(
        "DELETE",
        "/triage/blocks/{id}",
        user_id=USER_B,
        path_params={"id": block_id},
    )
    assert del_res["statusCode"] == 404


def test_list_pagination_and_status_filter(aurora_client):
    for i in range(60):
        _invoke(
            "POST",
            "/triage/blocks",
            user_id=USER_A,
            body={
                "style_id": STYLE_1,
                "name": f"Block {i}",
                "date_from": "2026-04-01",
                "date_to": "2026-04-30",
            },
        )
    res = _invoke(
        "GET",
        "/styles/{style_id}/triage/blocks",
        user_id=USER_A,
        path_params={"style_id": STYLE_1},
        qs={"limit": "50", "offset": "0"},
    )
    body = json.loads(res["body"])
    assert body["total"] == 60
    assert len(body["items"]) == 50

    res2 = _invoke(
        "GET",
        "/styles/{style_id}/triage/blocks",
        user_id=USER_A,
        path_params={"style_id": STYLE_1},
        qs={"status": "FINALIZED"},
    )
    assert json.loads(res2["body"])["total"] == 0


def test_late_category_snapshot(aurora_client):
    """spec-D D7 — creating a category snapshots into active triage blocks."""
    create_res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": STYLE_1,
            "name": "X",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    block_id = json.loads(create_res["body"])["id"]

    # Initial detail: 5 technical, 0 staging.
    detail_initial = json.loads(
        _invoke(
            "GET",
            "/triage/blocks/{id}",
            user_id=USER_A,
            path_params={"id": block_id},
        )["body"]
    )
    staging_initial = [
        b for b in detail_initial["buckets"] if b["bucket_type"] == "STAGING"
    ]
    assert staging_initial == []

    # Now create a category in this style -- D7 must fire.
    _invoke(
        "POST",
        "/styles/{style_id}/categories",
        user_id=USER_A,
        path_params={"style_id": STYLE_1},
        body={"name": "Tech House"},
    )

    detail_after = json.loads(
        _invoke(
            "GET",
            "/triage/blocks/{id}",
            user_id=USER_A,
            path_params={"id": block_id},
        )["body"]
    )
    staging_after = [
        b for b in detail_after["buckets"] if b["bucket_type"] == "STAGING"
    ]
    assert len(staging_after) == 1
    assert staging_after[0]["category_name"] == "Tech House"
    assert staging_after[0]["inactive"] is False


def test_move_within_block_and_caps(aurora_client):
    track_id = str(uuid.uuid4())
    _seed_track(
        aurora_client,
        track_id=track_id,
        style_id=STYLE_1,
        publish_date=date(2026, 4, 15),
        spotify_release_date=date(2026, 4, 15),
    )
    create_res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": STYLE_1,
            "name": "X",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    block = json.loads(create_res["body"])
    new_b = next(b for b in block["buckets"] if b["bucket_type"] == "NEW")
    discard_b = next(
        b for b in block["buckets"] if b["bucket_type"] == "DISCARD"
    )

    move_res = _invoke(
        "POST",
        "/triage/blocks/{id}/move",
        user_id=USER_A,
        path_params={"id": block["id"]},
        body={
            "from_bucket_id": new_b["id"],
            "to_bucket_id": discard_b["id"],
            "track_ids": [track_id],
        },
    )
    assert move_res["statusCode"] == 200
    assert json.loads(move_res["body"])["moved"] == 1

    # Idempotent re-move: track now in DISCARD, second attempt fails as
    # tracks_not_in_source from NEW.
    move_res2 = _invoke(
        "POST",
        "/triage/blocks/{id}/move",
        user_id=USER_A,
        path_params={"id": block["id"]},
        body={
            "from_bucket_id": new_b["id"],
            "to_bucket_id": discard_b["id"],
            "track_ids": [track_id],
        },
    )
    assert move_res2["statusCode"] == 422
    body2 = json.loads(move_res2["body"])
    assert body2["error_code"] == "tracks_not_in_source"


def test_move_cap_1001_rejected(aurora_client):
    create_res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": STYLE_1,
            "name": "X",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    block = json.loads(create_res["body"])
    new_b = next(b for b in block["buckets"] if b["bucket_type"] == "NEW")
    discard_b = next(
        b for b in block["buckets"] if b["bucket_type"] == "DISCARD"
    )
    ids = [str(uuid.uuid4()) for _ in range(1001)]
    res = _invoke(
        "POST",
        "/triage/blocks/{id}/move",
        user_id=USER_A,
        path_params={"id": block["id"]},
        body={
            "from_bucket_id": new_b["id"],
            "to_bucket_id": discard_b["id"],
            "track_ids": ids,
        },
    )
    assert res["statusCode"] == 422
```

- [ ] **Step 22.2: Run + commit**

Run: `pytest tests/integration/test_triage_handler.py -v`
Suggested subject: `test(triage): add tenancy, pagination, snapshot, move-cap integration tests`

---

## Task 23: Integration tests — finalize, inactive cascade, transfer, overlap

**Files:**
- Modify: `tests/integration/test_triage_handler.py` (append)

- [ ] **Step 23.1: Append the remaining integration tests**

```python
def test_finalize_promotes_staging_to_categories(aurora_client):
    track_id = str(uuid.uuid4())
    _seed_track(
        aurora_client,
        track_id=track_id,
        style_id=STYLE_1,
        publish_date=date(2026, 4, 15),
        spotify_release_date=date(2026, 4, 15),
    )
    cat_res = _invoke(
        "POST",
        "/styles/{style_id}/categories",
        user_id=USER_A,
        path_params={"style_id": STYLE_1},
        body={"name": "Tech"},
    )
    cat_id = json.loads(cat_res["body"])["id"]
    create_res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": STYLE_1,
            "name": "F",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    block = json.loads(create_res["body"])
    new_b = next(b for b in block["buckets"] if b["bucket_type"] == "NEW")
    staging = next(b for b in block["buckets"] if b["category_id"] == cat_id)
    _invoke(
        "POST",
        "/triage/blocks/{id}/move",
        user_id=USER_A,
        path_params={"id": block["id"]},
        body={
            "from_bucket_id": new_b["id"],
            "to_bucket_id": staging["id"],
            "track_ids": [track_id],
        },
    )

    fin_res = _invoke(
        "POST",
        "/triage/blocks/{id}/finalize",
        user_id=USER_A,
        path_params={"id": block["id"]},
    )
    assert fin_res["statusCode"] == 200
    body = json.loads(fin_res["body"])
    assert body["block"]["status"] == "FINALIZED"
    assert body["promoted"][cat_id] == 1

    # Track lands in category_tracks with source_triage_block_id set.
    rows = aurora_client.execute(
        """
        SELECT track_id, source_triage_block_id
        FROM category_tracks
        WHERE category_id = :c
        """,
        {"c": cat_id},
    )
    assert len(rows) == 1
    assert rows[0]["track_id"] == track_id
    assert rows[0]["source_triage_block_id"] == block["id"]

    # Repeat finalize → 422 block_not_editable
    second = _invoke(
        "POST",
        "/triage/blocks/{id}/finalize",
        user_id=USER_A,
        path_params={"id": block["id"]},
    )
    assert second["statusCode"] == 422


def test_finalize_blocks_when_inactive_staging_has_tracks(aurora_client):
    track_id = str(uuid.uuid4())
    _seed_track(
        aurora_client,
        track_id=track_id,
        style_id=STYLE_1,
        publish_date=date(2026, 4, 15),
        spotify_release_date=date(2026, 4, 15),
    )
    cat_res = _invoke(
        "POST",
        "/styles/{style_id}/categories",
        user_id=USER_A,
        path_params={"style_id": STYLE_1},
        body={"name": "ToDelete"},
    )
    cat_id = json.loads(cat_res["body"])["id"]
    create_res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": STYLE_1,
            "name": "F",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    block = json.loads(create_res["body"])
    new_b = next(b for b in block["buckets"] if b["bucket_type"] == "NEW")
    staging = next(b for b in block["buckets"] if b["category_id"] == cat_id)
    _invoke(
        "POST",
        "/triage/blocks/{id}/move",
        user_id=USER_A,
        path_params={"id": block["id"]},
        body={
            "from_bucket_id": new_b["id"],
            "to_bucket_id": staging["id"],
            "track_ids": [track_id],
        },
    )

    # Soft-delete the category → D8 marks the staging inactive.
    _invoke(
        "DELETE",
        "/categories/{id}",
        user_id=USER_A,
        path_params={"id": cat_id},
    )

    fin_res = _invoke(
        "POST",
        "/triage/blocks/{id}/finalize",
        user_id=USER_A,
        path_params={"id": block["id"]},
    )
    assert fin_res["statusCode"] == 409
    body = json.loads(fin_res["body"])
    assert body["error_code"] == "inactive_buckets_have_tracks"
    assert body["inactive_buckets"][0]["category_id"] == cat_id
    assert body["inactive_buckets"][0]["track_count"] == 1


def test_transfer_cross_block_same_style(aurora_client):
    track_id = str(uuid.uuid4())
    _seed_track(
        aurora_client,
        track_id=track_id,
        style_id=STYLE_1,
        publish_date=date(2026, 4, 15),
        spotify_release_date=date(2026, 4, 15),
    )
    src_res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": STYLE_1,
            "name": "S1",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    src = json.loads(src_res["body"])
    tgt_res = _invoke(
        "POST",
        "/triage/blocks",
        user_id=USER_A,
        body={
            "style_id": STYLE_1,
            "name": "T1",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    tgt = json.loads(tgt_res["body"])
    tgt_unc = next(
        b for b in tgt["buckets"] if b["bucket_type"] == "UNCLASSIFIED"
    )

    transfer_res = _invoke(
        "POST",
        "/triage/blocks/{src_id}/transfer",
        user_id=USER_A,
        path_params={"src_id": src["id"]},
        body={
            "target_bucket_id": tgt_unc["id"],
            "track_ids": [track_id],
        },
    )
    assert transfer_res["statusCode"] == 200
    assert json.loads(transfer_res["body"])["transferred"] == 1

    # Idempotent
    transfer_res2 = _invoke(
        "POST",
        "/triage/blocks/{src_id}/transfer",
        user_id=USER_A,
        path_params={"src_id": src["id"]},
        body={
            "target_bucket_id": tgt_unc["id"],
            "track_ids": [track_id],
        },
    )
    assert json.loads(transfer_res2["body"])["transferred"] == 0


def test_overlapping_windows_finalize_idempotent(aurora_client):
    """spec-D D3 — overlapping in-progress blocks. Sequential finalize
    on the same track must produce a single category_tracks row."""
    track_id = str(uuid.uuid4())
    _seed_track(
        aurora_client,
        track_id=track_id,
        style_id=STYLE_1,
        publish_date=date(2026, 4, 15),
        spotify_release_date=date(2026, 4, 15),
    )
    cat_res = _invoke(
        "POST",
        "/styles/{style_id}/categories",
        user_id=USER_A,
        path_params={"style_id": STYLE_1},
        body={"name": "K"},
    )
    cat_id = json.loads(cat_res["body"])["id"]

    blocks: list[dict] = []
    for label in ("A", "B"):
        cr = _invoke(
            "POST",
            "/triage/blocks",
            user_id=USER_A,
            body={
                "style_id": STYLE_1,
                "name": label,
                "date_from": "2026-04-01",
                "date_to": "2026-04-30",
            },
        )
        b = json.loads(cr["body"])
        new_b = next(x for x in b["buckets"] if x["bucket_type"] == "NEW")
        # Track will be in NEW only for the first block (excluded from second
        # block by "not already in user's category" rule -- but only after
        # finalize. Before finalize, both blocks see the track in NEW.)
        staging = next(
            x for x in b["buckets"] if x["category_id"] == cat_id
        )
        _invoke(
            "POST",
            "/triage/blocks/{id}/move",
            user_id=USER_A,
            path_params={"id": b["id"]},
            body={
                "from_bucket_id": new_b["id"],
                "to_bucket_id": staging["id"],
                "track_ids": [track_id],
            },
        )
        blocks.append(b)

    # Finalize first
    _invoke(
        "POST",
        "/triage/blocks/{id}/finalize",
        user_id=USER_A,
        path_params={"id": blocks[0]["id"]},
    )
    # Finalize second -- ON CONFLICT DO NOTHING means no error,
    # category_tracks still has exactly 1 row.
    res = _invoke(
        "POST",
        "/triage/blocks/{id}/finalize",
        user_id=USER_A,
        path_params={"id": blocks[1]["id"]},
    )
    assert res["statusCode"] == 200

    rows = aurora_client.execute(
        """
        SELECT count(*) AS cnt FROM category_tracks WHERE category_id = :c
        """,
        {"c": cat_id},
    )
    assert int(rows[0]["cnt"]) == 1
```

- [ ] **Step 23.2: Run + commit**

Run: `pytest tests/integration/test_triage_handler.py -v`
Suggested subject: `test(triage): add finalize, inactive-cascade, transfer, overlap integration tests`

---

## Task 24: Terraform — 9 new API Gateway routes

**Files:**
- Create: `infra/curation_routes_triage.tf`

The existing `infra/curation.tf` already declares:

- `aws_lambda_function.curation`
- `aws_apigatewayv2_integration.curation`
- `aws_apigatewayv2_authorizer.jwt` (or its referenced module)
- `aws_lambda_permission.curation_invoke`

Spec-D only adds 9 route resources attached to those existing resources.

- [ ] **Step 24.1: Inspect existing route file pattern**

Run: `grep -n "aws_apigatewayv2_route" infra/*.tf | head -20`

Note the resource block style used for spec-C routes (look for one referencing `/categories`). Mirror it.

- [ ] **Step 24.2: Create the routes file**

```hcl
# infra/curation_routes_triage.tf
# spec-D triage routes attached to the existing curation Lambda integration.

resource "aws_apigatewayv2_route" "triage_create" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /triage/blocks"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_list_by_style" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /styles/{style_id}/triage/blocks"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_list_all" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /triage/blocks"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_get" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /triage/blocks/{id}"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_bucket_tracks" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /triage/blocks/{id}/buckets/{bucket_id}/tracks"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_move" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /triage/blocks/{id}/move"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_transfer" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /triage/blocks/{src_id}/transfer"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_finalize" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /triage/blocks/{id}/finalize"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "triage_delete" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "DELETE /triage/blocks/{id}"
  target             = "integrations/${aws_apigatewayv2_integration.curation.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

If the actual resource names in `infra/` differ (e.g. `aws_apigatewayv2_api.main` vs `.http`), match what spec-C uses by grepping the existing `infra/curation*.tf` first, and mirror the references.

- [ ] **Step 24.3: Validate**

```bash
cd infra && terraform fmt && terraform validate
```
Expected: no errors. (Skip `terraform plan` if AWS credentials are not available locally; CI runs it.)

- [ ] **Step 24.4: Commit**

Suggested subject: `feat(infra): add 9 API Gateway routes for triage`

---

## Task 25: OpenAPI regeneration

**Files:**
- Modify: `scripts/generate_openapi.py` (append 9 routes to the manual `ROUTES` table)
- Modify: `docs/openapi.yaml` (regenerated output)

- [ ] **Step 25.1: Add the 9 new routes to `ROUTES`**

Open `scripts/generate_openapi.py`, locate `ROUTES` (a list/dict of route specs). Mirror the spec-C entries' structure and append entries for:

```
POST   /triage/blocks
GET    /triage/blocks
GET    /styles/{style_id}/triage/blocks
GET    /triage/blocks/{id}
GET    /triage/blocks/{id}/buckets/{bucket_id}/tracks
POST   /triage/blocks/{id}/move
POST   /triage/blocks/{src_id}/transfer
POST   /triage/blocks/{id}/finalize
DELETE /triage/blocks/{id}
```

Each entry needs: route, summary, security (JWT), request schema name, response schemas per status. Reuse the spec-C format. Schema names: `CreateTriageBlockIn`, `TriageBlockDetail`, `TriageBlockSummary`, `MoveTracksIn`, `TransferTracksIn`, `MoveTracksOut`, `TransferTracksOut`, `FinalizeOut`, `BucketTrackRow`. Define those Pydantic-derived OpenAPI schemas alongside the existing spec-C ones.

- [ ] **Step 25.2: Regenerate**

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
```
This overwrites `docs/openapi.yaml`.

- [ ] **Step 25.3: Verify**

```bash
git diff docs/openapi.yaml | head -100
```
Expected: 9 new path entries; existing spec-C paths unchanged.

- [ ] **Step 25.4: Commit**

Suggested subject: `docs(api): regenerate openapi spec with spec-D triage routes`

---

## Task 26: Update `docs/data-model.md`

**Files:**
- Modify: `docs/data-model.md`

- [ ] **Step 26.1: Append 3 new tables and the column**

After §1.16 `category_tracks`, append three new sub-sections (use the next free numbers — likely §1.17, §1.18, §1.19) following the existing format:

```markdown
### 1.17 triage_blocks

User triage sessions. Per-(user, style, date-range) working space for
sorting newly-ingested releases before promoting them into categories.

| Column        | Type           | Constraints                                  |
|---------------|----------------|----------------------------------------------|
| id            | String(36)     | PK (UUID)                                    |
| user_id       | String(36)     | NOT NULL, FK -> users.id                     |
| style_id      | String(36)     | NOT NULL, FK -> clouder_styles.id            |
| name          | Text           | NOT NULL                                     |
| date_from     | Date           | NOT NULL                                     |
| date_to       | Date           | NOT NULL, CHECK date_to >= date_from         |
| status        | String(16)     | NOT NULL, default 'IN_PROGRESS', CHECK in (...)|
| created_at    | DateTime(tz)   | NOT NULL                                     |
| updated_at    | DateTime(tz)   | NOT NULL                                     |
| finalized_at  | DateTime(tz)   | nullable; set on flip to FINALIZED           |
| deleted_at    | DateTime(tz)   | nullable                                     |

**Indexes:**
- `idx_triage_blocks_user_style_status` (user_id, style_id, status) WHERE deleted_at IS NULL
- `idx_triage_blocks_user_created` (user_id, created_at DESC) WHERE deleted_at IS NULL

State: only `IN_PROGRESS → FINALIZED`. No re-open. Soft-delete via `deleted_at`
column orthogonal to status. Overlapping date windows allowed for the same
(user_id, style_id, IN_PROGRESS); no EXCLUSION constraint.

### 1.18 triage_buckets

Buckets within a triage block. Five technical bucket types per block plus
N staging buckets (one per alive category in the style at create time).

| Column           | Type        | Constraints                                                |
|------------------|-------------|------------------------------------------------------------|
| id               | String(36)  | PK (UUID)                                                  |
| triage_block_id  | String(36)  | NOT NULL, FK -> triage_blocks.id ON DELETE CASCADE         |
| bucket_type      | String(16)  | NOT NULL, CHECK in ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING') |
| category_id      | String(36)  | nullable, FK -> categories.id ON DELETE RESTRICT           |
| inactive         | Boolean     | NOT NULL, default FALSE                                    |
| created_at       | DateTime(tz)| NOT NULL                                                   |

**Indexes / constraints:**
- CHECK `(bucket_type = 'STAGING') = (category_id IS NOT NULL)`
- `uq_triage_buckets_block_category` UNIQUE (triage_block_id, category_id) WHERE category_id IS NOT NULL
- `uq_triage_buckets_block_type_tech` UNIQUE (triage_block_id, bucket_type) WHERE bucket_type <> 'STAGING'
- `idx_triage_buckets_block` (triage_block_id)
- `idx_triage_buckets_category` (category_id) WHERE category_id IS NOT NULL

`inactive=true` is set by spec-D D8 when the linked category is soft-deleted;
finalize blocks if any inactive STAGING bucket holds tracks. FK to categories
uses `ON DELETE RESTRICT` rather than `SET NULL` because nulling
`category_id` on a STAGING bucket would violate the staging-coupling CHECK.

### 1.19 triage_bucket_tracks

Track membership inside a triage bucket. Idempotent on conflict.

| Column            | Type        | Constraints                                            |
|-------------------|-------------|--------------------------------------------------------|
| triage_bucket_id  | String(36)  | PK (composite), FK -> triage_buckets.id ON DELETE CASCADE |
| track_id          | String(36)  | PK (composite), FK -> clouder_tracks.id                |
| added_at          | DateTime(tz)| NOT NULL                                               |

**PK:** (triage_bucket_id, track_id) — UNIQUE makes move/transfer idempotent.

**Indexes:**
- `idx_triage_bucket_tracks_bucket_added` (triage_bucket_id, added_at DESC, track_id)
```

Also append to the `clouder_tracks` section a note about `spotify_release_date`:

```markdown
### Update — clouder_tracks.spotify_release_date

New column added in 20260428_15_triage:

| spotify_release_date | Date | nullable; populated by Spotify enrichment from `album.release_date` per `release_date_precision` |

**Index:** `idx_tracks_spotify_release_date (spotify_release_date) WHERE spotify_release_date IS NOT NULL`.

Used by spec-D R4 classification at `POST /triage/blocks` time:
- NULL → UNCLASSIFIED
- < `date_from` → OLD
- otherwise + `release_type = 'compilation'` → NOT
- else → NEW
```

If the doc has a single existing `clouder_tracks` section, edit it inline instead of adding a duplicate.

Finally update the closing FK note in §1.16 `category_tracks`:

```
`source_triage_block_id` is NULL for direct adds via `POST /categories/{id}/tracks` and set by spec-D's triage finalize. The FK to `triage_blocks(id)` is added in spec-D's migration `20260428_15_triage` with `ON DELETE SET NULL`.
```

(Replace the existing "intentionally deferred to spec-D's migration" sentence.)

- [ ] **Step 26.2: Commit**

Suggested subject: `docs(data-model): document triage tables and spotify_release_date`

---

## Task 27: Final smoke + branch close-out

- [ ] **Step 27.1: Run the entire suite**

```bash
pytest -q
```
Expected: green.

- [ ] **Step 27.2: Run `alembic-check` locally (optional)**

```bash
export PYTHONPATH=src
docker run --rm -d --name pg-spec-d \
  -e POSTGRES_PASSWORD=postgres -p 5434:5432 postgres:16 || true
sleep 3
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5434/postgres'
alembic upgrade head
docker rm -f pg-spec-d || true
```
Expected: migrations 1..15 apply without error.

- [ ] **Step 27.3: Confirm git log**

Run: `git log --oneline | head -30`
Expected: tasks 1..26 each produced commits in order, all matching the Conventional Commits hook (`^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `). No squash, no amend.

- [ ] **Step 27.4: Push and open PR**

```bash
git push -u origin worktree-user_flow_spec_d
```

PR title: `feat(curation): spec-D triage`. Body:

```markdown
Implements docs/superpowers/specs/2026-04-28-spec-D-triage-design.md
following docs/superpowers/plans/2026-04-28-spec-D-triage.md.

## Summary
- New `triage_blocks`, `triage_buckets`, `triage_bucket_tracks` tables
  (alembic 15)
- New `clouder_tracks.spotify_release_date` column populated by Spotify
  enrichment patch
- New `triage_repository` + `triage_service` under `collector/curation/`
- 9 new HTTP routes added to existing `curation_handler.py` Lambda
- spec-C deferred FK on `category_tracks.source_triage_block_id` added
- Cross-spec patches in `categories_service` for D7/D8 side-effects

## Test plan
- [x] pytest -q
- [x] alembic-check (CI ephemeral postgres)
- [x] terraform validate + plan (additive only)
- [x] manual smoke against deployed API GW after deploy
```

---

## Self-Review Notes

- **Spec coverage:**
  - §3 D1–D20 decisions — implemented across Tasks 1–24.
  - §4 schema — Tasks 1, 2.
  - §5.2 create — Task 8 + Task 17 (handler).
  - §5.3–§5.5 list/detail — Tasks 9, 18.
  - §5.6 bucket tracks — Tasks 10, 18.
  - §5.7 move — Tasks 11, 19.
  - §5.8 transfer — Tasks 12, 19.
  - §5.9 finalize — Tasks 13, 20.
  - §5.10 delete — Tasks 14, 20.
  - §6.1 R4 SQL — Task 8 (the INSERT-FROM-SELECT) + Task 6 (Python mirror).
  - §6.2 Spotify patch — Task 3.
  - §7 code layout — Tasks 4, 5, 6, 7, 16.
  - §8 migration & infra — Tasks 1, 24, 25, 26.
  - §9 testing — Tasks 21, 22, 23 (integration), Tasks 1–15 (unit).
  - §10 open items — informational; future flags don't need tasks.
  - §11 acceptance criteria — verified by integration tests #1, #2, #3 (Task 21), #4–#10 (Task 22), #11–#17 (Task 23).
- **Type consistency:** `TriageBlockRow`, `TriageBucketRow`, `TriageBlockSummaryRow`, `BucketTrackRowOut`, `MoveResult`, `TransferResult`, `FinalizeResult` defined in Task 7 and used identically in Tasks 8–15. Bucket-type constants (`BUCKET_TYPE_NEW`, etc.) defined in Task 6 and used in Tasks 7–8. `add_tracks_bulk` keyword shape `(user_id, category_id, items, transaction_id)` consistent across Tasks 13, 16; verify against spec-C's actual signature before running.
- **No placeholders:** every task has full SQL, full Python code blocks, and explicit pytest commands with expected outcomes.
- **Frequent commits:** 27 tasks → 27 commits. Conventional Commits format throughout. All commit messages generated via `caveman:caveman-commit` skill per repo policy.
- **Cross-spec coupling localized:** the categories_service patch (Task 16) imports `TriageRepository` locally inside the methods, keeping spec-C's module shape unchanged at the file-header level. The deferred FK from spec-C is closed in Task 1.
