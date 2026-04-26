# spec-C Categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the user-curation Layer-1 (`categories` + `category_tracks`) end-to-end: schema, repository, Lambda handler with 9 routes, infrastructure, and tests. After this plan ships, a logged-in user can manage permanent per-style track libraries via JWT-gated REST endpoints, and spec-D obtains the `add_tracks_bulk(...)` repository contract it needs for triage finalize.

**Architecture:** New Lambda `curation_handler.py` calls a new `CategoriesRepository` in `collector/curation/`. Repository runs raw SQL through the existing Aurora Data API client (no SQLAlchemy at runtime). Tenancy is enforced at the repository layer (every method takes `user_id` and includes it in `WHERE`). All routes are JWT-gated by the existing API Gateway Lambda Authorizer from spec-A; `user_id` flows in via `event.requestContext.authorizer.lambda.user_id`. Service helpers do name normalization, validation, and reorder set-equality checks.

**Tech Stack:** Python 3.12 Lambda, Aurora Postgres via RDS Data API, Pydantic v2 schemas, Alembic migrations, Terraform (HTTP API Gateway v2), pytest with MagicMock-based unit tests + monkeypatched FakeRepo integration tests.

**Spec:** [`docs/superpowers/specs/2026-04-26-spec-C-categories-design.md`](../specs/2026-04-26-spec-C-categories-design.md)

---

## File Structure

**New files (created during this plan):**

```
alembic/versions/20260427_14_categories.py     # T1 — DDL migration
src/collector/curation/__init__.py              # T2 — shared types + errors
src/collector/curation/schemas.py               # T3 — Pydantic models
src/collector/curation/categories_service.py    # T4 — pure helpers
src/collector/curation/categories_repository.py # T5–T13 — Data API repo
src/collector/curation_handler.py               # T14–T22 — Lambda entry + 9 routes
tests/unit/test_migration_14_sql.py             # T1
tests/unit/test_curation_schemas.py             # T3
tests/unit/test_categories_service.py           # T4
tests/unit/test_categories_repository.py        # T5–T13
tests/integration/test_curation_handler.py      # T23–T27
infra/curation_lambda.tf                        # T28 — Lambda + integration
infra/curation_routes.tf                        # T29 — 9 routes + permission
```

**Modified files:**

```
docs/data-model.md                              # T30 — append §1.X for new tables
infra/main.tf or variables.tf                   # T28 — wire env vars (only if needed)
```

**Untouched (intentionally):**

- `src/collector/handler.py` — keep canonical-core read + admin ingest separate.
- `src/collector/repositories.py` — categories live in their own module.
- `src/collector/auth/*` — spec-A is the prerequisite; nothing changes here.

---

## Conventions

- **Python style:** existing code uses `from __future__ import annotations`, `dataclass(frozen=True)`, type hints everywhere. Match it.
- **SQL style:** raw SQL strings inside repository methods, parameters via `:name` placeholders, passed as `dict` to `data_api.execute(sql, params, transaction_id=...)`.
- **Datetime:** UTC always. `datetime.now(timezone.utc)`. There is a `utc_now()` helper in `collector/repositories.py:1194`; the curation package will define its own to avoid cross-imports.
- **UUIDs:** `str(uuid.uuid4())`. Always strings (length 36).
- **Errors:** custom exception classes in `collector/curation/__init__.py`, mapped to HTTP envelope `{error_code, message, correlation_id}` by the handler.
- **Logging:** `from collector.logging_utils import log_event`. Always pass `correlation_id`.
- **Commits:** Conventional Commits (`feat`, `fix`, `test`, `docs`, `chore`, ...). Hook in repo blocks subjects that don't match `^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `. Use `caveman:caveman-commit` skill when preparing commit messages — repo policy.
- **Branch:** work happens on the existing worktree branch `worktree-user_flow_spec_c`.

---

## Task 1: Alembic migration for `categories` and `category_tracks`

**Files:**
- Create: `alembic/versions/20260427_14_categories.py`
- Test: `tests/unit/test_migration_14_sql.py`

- [ ] **Step 1.1: Write the migration file**

```python
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
```

- [ ] **Step 1.2: Verify `down_revision` matches the latest migration**

Run: `ls alembic/versions/ | sort | tail -3`
Confirm latest is `20260426_13_user_vendor_tokens.py`. If not, update `down_revision` in the migration to whatever the actual latest revision id is.

- [ ] **Step 1.3: Write the SQL-text test**

```python
# tests/unit/test_migration_14_sql.py
"""Test that the categories migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260427_14_categories.py")
    spec = importlib.util.spec_from_file_location("mig14", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260427_14"
    assert mig.down_revision == "20260426_13"


def test_upgrade_creates_categories_table() -> None:
    src = Path("alembic/versions/20260427_14_categories.py").read_text()
    assert 'create_table(\n        "categories"' in src
    assert '"normalized_name"' in src
    assert '"position"' in src
    assert '"deleted_at"' in src
    assert "uq_categories_user_style_normname" in src
    assert "deleted_at IS NULL" in src
    assert "idx_categories_user_style_position" in src
    assert "idx_categories_user_created" in src


def test_upgrade_creates_category_tracks_table() -> None:
    src = Path("alembic/versions/20260427_14_categories.py").read_text()
    assert 'create_table(\n        "category_tracks"' in src
    assert '"source_triage_block_id"' in src
    assert "PrimaryKeyConstraint(\"category_id\", \"track_id\")" in src
    assert "idx_category_tracks_category_added" in src


def test_no_fk_on_source_triage_block_id() -> None:
    """spec-D adds the FK; spec-C must not."""
    src = Path("alembic/versions/20260427_14_categories.py").read_text()
    # No FK constraint targeting triage_blocks in this migration.
    assert "triage_blocks" not in src
```

- [ ] **Step 1.4: Run the migration test**

Run: `pytest tests/unit/test_migration_14_sql.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 1.5: Run the full unit suite to confirm nothing broke**

Run: `pytest tests/unit/ -q`
Expected: existing suite still green plus the 4 new tests.

- [ ] **Step 1.6: Commit**

```bash
git add alembic/versions/20260427_14_categories.py tests/unit/test_migration_14_sql.py
git commit -m "feat(curation): add categories migration"
```

---

## Task 2: Curation package skeleton + custom errors

**Files:**
- Create: `src/collector/curation/__init__.py`

- [ ] **Step 2.1: Write `__init__.py` with shared types and errors**

```python
"""Curation user-overlay package: categories (spec-C), triage (spec-D), release-playlists (spec-E).

This module exposes only the cross-cutting types and errors shared by
all curation specs. Per-spec implementation lives in sibling modules
(`categories_repository.py`, `categories_service.py`, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PaginatedResult(Generic[T]):
    items: Sequence[T]
    total: int
    limit: int
    offset: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CurationError(Exception):
    """Base for curation-domain errors raised by repositories/services."""

    error_code: str = "curation_error"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(CurationError):
    error_code = "validation_error"
    http_status = 422


class NotFoundError(CurationError):
    http_status = 404

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class NameConflictError(CurationError):
    error_code = "name_conflict"
    http_status = 409


class OrderMismatchError(CurationError):
    error_code = "order_mismatch"
    http_status = 422
```

- [ ] **Step 2.2: Run a smoke import to verify the package loads**

Run: `python -c "from collector.curation import PaginatedResult, utc_now, ValidationError, NotFoundError, NameConflictError, OrderMismatchError; print('ok')"`
Set `PYTHONPATH=src` first if needed: `PYTHONPATH=src python -c "..."`
Expected: prints `ok`.

- [ ] **Step 2.3: Commit**

```bash
git add src/collector/curation/__init__.py
git commit -m "feat(curation): add curation package skeleton"
```

---

## Task 3: Pydantic schemas

**Files:**
- Create: `src/collector/curation/schemas.py`
- Test: `tests/unit/test_curation_schemas.py`

- [ ] **Step 3.1: Write the failing schema test**

```python
# tests/unit/test_curation_schemas.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.curation.schemas import (
    AddTrackIn,
    CreateCategoryIn,
    RenameCategoryIn,
    ReorderCategoriesIn,
)


def test_create_category_in_accepts_name() -> None:
    obj = CreateCategoryIn.model_validate({"name": "Tech House"})
    assert obj.name == "Tech House"


def test_create_category_in_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CreateCategoryIn.model_validate({"name": "x", "style_id": "y"})


def test_rename_category_in_accepts_name() -> None:
    obj = RenameCategoryIn.model_validate({"name": "Deep"})
    assert obj.name == "Deep"


def test_reorder_in_accepts_id_array() -> None:
    obj = ReorderCategoriesIn.model_validate(
        {"category_ids": ["a", "b", "c"]}
    )
    assert obj.category_ids == ["a", "b", "c"]


def test_reorder_in_rejects_non_string_ids() -> None:
    with pytest.raises(ValidationError):
        ReorderCategoriesIn.model_validate({"category_ids": [1, 2]})


def test_reorder_in_rejects_missing_field() -> None:
    with pytest.raises(ValidationError):
        ReorderCategoriesIn.model_validate({})


def test_add_track_in_accepts_track_id() -> None:
    obj = AddTrackIn.model_validate({"track_id": "track-uuid"})
    assert obj.track_id == "track-uuid"
```

- [ ] **Step 3.2: Run to verify failure**

Run: `pytest tests/unit/test_curation_schemas.py -v`
Expected: ImportError — `schemas` module not yet created.

- [ ] **Step 3.3: Implement `schemas.py`**

```python
"""Request schemas for curation HTTP endpoints (spec-C)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class CreateCategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class RenameCategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class ReorderCategoriesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_ids: List[str]


class AddTrackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_id: str = Field(min_length=1)
```

- [ ] **Step 3.4: Run to verify pass**

Run: `pytest tests/unit/test_curation_schemas.py -v`
Expected: 7 tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/collector/curation/schemas.py tests/unit/test_curation_schemas.py
git commit -m "feat(curation): add pydantic schemas for spec-C requests"
```

---

## Task 4: Service helpers — name normalization, validation, reorder set check

**Files:**
- Create: `src/collector/curation/categories_service.py`
- Test: `tests/unit/test_categories_service.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/unit/test_categories_service.py
from __future__ import annotations

import pytest

from collector.curation import OrderMismatchError, ValidationError
from collector.curation.categories_service import (
    normalize_category_name,
    validate_category_name,
    validate_reorder_set,
)


# ---- normalize_category_name -----------------------------------------------

def test_normalize_lowercases_and_trims() -> None:
    assert normalize_category_name("  Tech House  ") == "tech house"


def test_normalize_collapses_internal_whitespace() -> None:
    assert normalize_category_name("Tech    House") == "tech house"


def test_normalize_handles_unicode() -> None:
    assert normalize_category_name("Délicat") == "délicat"


def test_normalize_handles_emoji() -> None:
    assert normalize_category_name("Hot 🔥 House") == "hot 🔥 house"


def test_normalize_pure_whitespace_yields_empty() -> None:
    assert normalize_category_name("   \t  ") == ""


# ---- validate_category_name ------------------------------------------------

def test_validate_accepts_normal_name() -> None:
    validate_category_name("Tech House")  # no exception


def test_validate_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("")


def test_validate_rejects_whitespace_only() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("   ")


def test_validate_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("x" * 65)


def test_validate_accepts_64_chars() -> None:
    validate_category_name("x" * 64)


def test_validate_rejects_control_chars() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("Tech\x00House")


def test_validate_rejects_newlines() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("Tech\nHouse")


# ---- validate_reorder_set --------------------------------------------------

def test_reorder_set_passes_on_exact_match() -> None:
    validate_reorder_set(actual={"a", "b", "c"}, requested=["a", "b", "c"])


def test_reorder_set_passes_on_reordered_match() -> None:
    validate_reorder_set(actual={"a", "b", "c"}, requested=["c", "a", "b"])


def test_reorder_set_rejects_missing_id() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b", "c"}, requested=["a", "b"])


def test_reorder_set_rejects_extra_id() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b"}, requested=["a", "b", "c"])


def test_reorder_set_rejects_duplicates() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b"}, requested=["a", "a"])
```

- [ ] **Step 4.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_service.py -v`
Expected: ImportError.

- [ ] **Step 4.3: Implement `categories_service.py`**

```python
"""Pure helpers for spec-C categories: normalization, validation, reorder checks."""

from __future__ import annotations

from typing import Iterable, Sequence

from . import OrderMismatchError, ValidationError


_MAX_NAME_LENGTH = 64


def normalize_category_name(name: str) -> str:
    """Lowercase + trim + collapse internal whitespace.

    Used for the UNIQUE check on (user_id, style_id, normalized_name).
    The original `name` is preserved separately for display.
    """
    return " ".join(name.strip().lower().split())


def validate_category_name(name: str) -> None:
    """Raise ValidationError if the name is unacceptable.

    Rules:
        - Non-empty after trim
        - No more than 64 chars after trim
        - No control characters (ord < 0x20 or ord == 0x7F)
    """
    trimmed = name.strip()
    if not trimmed:
        raise ValidationError("Name must be non-empty")
    if len(trimmed) > _MAX_NAME_LENGTH:
        raise ValidationError(
            f"Name must be at most {_MAX_NAME_LENGTH} characters"
        )
    for ch in trimmed:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValidationError("Name must not contain control characters")


def validate_reorder_set(
    *, actual: Iterable[str], requested: Sequence[str]
) -> None:
    """Ensure the requested id list equals the actual alive set, no dups.

    Used by PUT /styles/{style_id}/categories/order. Either:
        - missing id (some current category not listed)
        - extra id (foreign / soft-deleted / wrong style)
        - duplicates within `requested`
    yields OrderMismatchError.
    """
    actual_set = set(actual)
    requested_set = set(requested)
    if len(requested) != len(requested_set):
        raise OrderMismatchError(
            "category_ids contains duplicates"
        )
    if actual_set != requested_set:
        raise OrderMismatchError(
            "category_ids must equal the current set of categories"
        )
```

- [ ] **Step 4.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_service.py -v`
Expected: 17 tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/collector/curation/categories_service.py tests/unit/test_categories_service.py
git commit -m "feat(curation): add name normalization and reorder validation"
```

---

## Task 5: Repository skeleton — dataclasses, factory, error mapping

**Files:**
- Create: `src/collector/curation/categories_repository.py`
- Test: `tests/unit/test_categories_repository.py`

- [ ] **Step 5.1: Write failing skeleton test**

```python
# tests/unit/test_categories_repository.py
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
)
from collector.curation.categories_repository import (
    CategoriesRepository,
    CategoryRow,
    TrackInCategoryRow,
)


def _make() -> tuple[CategoriesRepository, MagicMock]:
    data_api = MagicMock()
    return CategoriesRepository(data_api=data_api), data_api


def _now() -> datetime:
    return datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)


def test_repository_constructs() -> None:
    repo, _ = _make()
    assert repo is not None


def test_category_row_dataclass_shape() -> None:
    row = CategoryRow(
        id="c1",
        user_id="u1",
        style_id="s1",
        style_name="House",
        name="Tech",
        normalized_name="tech",
        position=0,
        track_count=5,
        created_at="2026-04-27T12:00:00Z",
        updated_at="2026-04-27T12:00:00Z",
    )
    assert row.id == "c1"
    assert row.style_name == "House"
    assert row.track_count == 5


def test_track_in_category_row_dataclass_shape() -> None:
    row = TrackInCategoryRow(
        track={"id": "t1", "title": "X", "artists": ["A"]},
        added_at="2026-04-27T12:00:00Z",
        source_triage_block_id=None,
    )
    assert row.track["id"] == "t1"
    assert row.source_triage_block_id is None
```

- [ ] **Step 5.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: ImportError.

- [ ] **Step 5.3: Implement skeleton**

```python
# src/collector/curation/categories_repository.py
"""Aurora Data API repository for spec-C categories.

Tenancy: every method takes `user_id` and includes it in WHERE.
Cross-user access yields zero rows (mapped to 404 by the handler).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from collector.data_api import DataAPIClient
from collector.settings import get_data_api_settings

from . import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
    PaginatedResult,
    utc_now,
)


@dataclass(frozen=True)
class CategoryRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    normalized_name: str
    position: int
    track_count: int
    created_at: str  # ISO string from Data API
    updated_at: str


@dataclass(frozen=True)
class TrackInCategoryRow:
    track: Mapping[str, Any]
    added_at: str
    source_triage_block_id: str | None


class CategoriesRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # Methods filled in by Tasks 6–13.


def create_default_categories_repository() -> CategoriesRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return CategoriesRepository(data_api=data_api)
```

- [ ] **Step 5.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add categories repository skeleton"
```

---

## Task 6: Repository — `create`

`create` runs in a transaction: SELECT MAX(position), then INSERT. Maps `unique_violation` (Postgres SQLSTATE `23505` on `uq_categories_user_style_normname`) to `NameConflictError`. Verifies the style exists and raises `NotFoundError("style_not_found", ...)` otherwise.

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 6.1: Append failing test for `create`**

```python
# Append to tests/unit/test_categories_repository.py

def test_create_starts_transaction_and_inserts() -> None:
    repo, data_api = _make()

    # data_api.transaction() is a contextmanager yielding tx_id
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    # First call: style existence -> 1 row.
    # Second call: max(position) -> [{"max_pos": 2}].
    # Third call: insert returning row.
    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],
        [{"max_pos": 2}],
        [
            {
                "id": "c1",
                "user_id": "u1",
                "style_id": "s1",
                "style_name": "House",
                "name": "Tech",
                "normalized_name": "tech",
                "position": 3,
                "track_count": 0,
                "created_at": "2026-04-27T12:00:00Z",
                "updated_at": "2026-04-27T12:00:00Z",
            }
        ],
    ]

    row = repo.create(
        user_id="u1",
        style_id="s1",
        category_id="c1",
        name="Tech",
        normalized_name="tech",
        now=_now(),
    )

    assert row.id == "c1"
    assert row.position == 3
    # Three execute calls: style check, max-position, insert
    assert data_api.execute.call_count == 3
    style_sql = data_api.execute.call_args_list[0].args[0]
    assert "FROM clouder_styles" in style_sql
    max_sql = data_api.execute.call_args_list[1].args[0]
    assert "MAX(position)" in max_sql
    assert "deleted_at IS NULL" in max_sql
    insert_sql = data_api.execute.call_args_list[2].args[0]
    assert "INSERT INTO categories" in insert_sql
    assert "RETURNING" in insert_sql


def test_create_raises_style_not_found() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [[]]  # style lookup empty
    with pytest.raises(NotFoundError) as exc:
        repo.create(
            user_id="u1",
            style_id="missing",
            category_id="c1",
            name="Tech",
            normalized_name="tech",
            now=_now(),
        )
    assert exc.value.error_code == "style_not_found"


def test_create_maps_unique_violation_to_name_conflict() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False

    class FakeUniqueViolation(Exception):
        def __str__(self) -> str:
            return (
                "duplicate key value violates unique constraint "
                "\"uq_categories_user_style_normname\""
            )

    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],
        [{"max_pos": -1}],
        FakeUniqueViolation(),
    ]
    with pytest.raises(NameConflictError):
        repo.create(
            user_id="u1",
            style_id="s1",
            category_id="c1",
            name="Tech",
            normalized_name="tech",
            now=_now(),
        )
```

- [ ] **Step 6.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 3 new tests fail (`create` not yet implemented).

- [ ] **Step 6.3: Implement `create`**

Add to `CategoriesRepository`:

```python
    def create(
        self,
        *,
        user_id: str,
        style_id: str,
        category_id: str,
        name: str,
        normalized_name: str,
        now,  # datetime
    ) -> CategoryRow:
        with self._data_api.transaction() as tx_id:
            style_rows = self._data_api.execute(
                "SELECT id, name FROM clouder_styles WHERE id = :style_id",
                {"style_id": style_id},
                transaction_id=tx_id,
            )
            if not style_rows:
                raise NotFoundError("style_not_found", "Style not found")
            style_name = style_rows[0]["name"]

            max_rows = self._data_api.execute(
                """
                SELECT COALESCE(MAX(position), -1) AS max_pos
                FROM categories
                WHERE user_id = :user_id
                  AND style_id = :style_id
                  AND deleted_at IS NULL
                """,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            position = int(max_rows[0]["max_pos"]) + 1

            try:
                rows = self._data_api.execute(
                    """
                    INSERT INTO categories (
                        id, user_id, style_id, name, normalized_name,
                        position, created_at, updated_at, deleted_at
                    ) VALUES (
                        :id, :user_id, :style_id, :name, :normalized_name,
                        :position, :created_at, :updated_at, NULL
                    )
                    RETURNING id, user_id, style_id, name, normalized_name,
                              position,
                              :style_name AS style_name,
                              0 AS track_count,
                              created_at, updated_at
                    """,
                    {
                        "id": category_id,
                        "user_id": user_id,
                        "style_id": style_id,
                        "name": name,
                        "normalized_name": normalized_name,
                        "position": position,
                        "style_name": style_name,
                        "created_at": now,
                        "updated_at": now,
                    },
                    transaction_id=tx_id,
                )
            except Exception as exc:
                msg = str(exc)
                if "uq_categories_user_style_normname" in msg:
                    raise NameConflictError(
                        "Category name already exists in this style"
                    ) from exc
                raise

            row = rows[0]
            return CategoryRow(
                id=row["id"],
                user_id=row["user_id"],
                style_id=row["style_id"],
                style_name=row["style_name"],
                name=row["name"],
                normalized_name=row["normalized_name"],
                position=int(row["position"]),
                track_count=int(row["track_count"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
```

- [ ] **Step 6.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 6 tests PASS (3 skeleton + 3 create).

- [ ] **Step 6.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add categories repository create"
```

---

## Task 7: Repository — `get`, `list_by_style`, `list_all`

These three share a common SELECT shape (categories + JOIN clouder_styles + LEFT JOIN COUNT category_tracks). Implement once, reuse.

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 7.1: Append failing tests**

```python
# Append to tests/unit/test_categories_repository.py

def test_get_returns_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "c1",
            "user_id": "u1",
            "style_id": "s1",
            "style_name": "House",
            "name": "Tech",
            "normalized_name": "tech",
            "position": 0,
            "track_count": 4,
            "created_at": "2026-04-27T12:00:00Z",
            "updated_at": "2026-04-27T12:00:00Z",
        }
    ]
    row = repo.get(user_id="u1", category_id="c1")
    assert row is not None
    assert row.track_count == 4
    sql = data_api.execute.call_args.args[0]
    assert "WHERE c.id = :category_id" in sql
    assert "c.user_id = :user_id" in sql
    assert "c.deleted_at IS NULL" in sql


def test_get_returns_none_when_missing() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    row = repo.get(user_id="u1", category_id="missing")
    assert row is None


def test_list_by_style_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [
            {
                "id": "c1", "user_id": "u1", "style_id": "s1",
                "style_name": "House", "name": "Tech",
                "normalized_name": "tech", "position": 0,
                "track_count": 0,
                "created_at": "x", "updated_at": "x",
            }
        ],
        [{"total": 1}],
    ]
    result = repo.list_by_style(
        user_id="u1", style_id="s1", limit=50, offset=0
    )
    assert result.total == 1
    assert len(result.items) == 1
    list_sql = data_api.execute.call_args_list[0].args[0]
    assert "ORDER BY c.position ASC" in list_sql
    assert "c.deleted_at IS NULL" in list_sql


def test_list_all_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[], [{"total": 0}]]
    result = repo.list_all(user_id="u1", limit=50, offset=0)
    assert result.total == 0
    list_sql = data_api.execute.call_args_list[0].args[0]
    assert "ORDER BY c.created_at DESC" in list_sql
    assert "c.style_id" not in list_sql.split("WHERE")[1].split("ORDER BY")[0]
```

- [ ] **Step 7.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 4 new tests fail.

- [ ] **Step 7.3: Implement methods**

Add to `CategoriesRepository`:

```python
    _CATEGORY_SELECT = """
        SELECT
            c.id, c.user_id, c.style_id, c.name, c.normalized_name,
            c.position, c.created_at, c.updated_at,
            s.name AS style_name,
            COALESCE(t.cnt, 0) AS track_count
        FROM categories c
        JOIN clouder_styles s ON s.id = c.style_id
        LEFT JOIN (
            SELECT category_id, COUNT(*) AS cnt
            FROM category_tracks
            GROUP BY category_id
        ) t ON t.category_id = c.id
    """

    def _row(self, raw: Mapping[str, Any]) -> CategoryRow:
        return CategoryRow(
            id=raw["id"],
            user_id=raw["user_id"],
            style_id=raw["style_id"],
            style_name=raw["style_name"],
            name=raw["name"],
            normalized_name=raw["normalized_name"],
            position=int(raw["position"]),
            track_count=int(raw["track_count"]),
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
        )

    def get(
        self, *, user_id: str, category_id: str
    ) -> CategoryRow | None:
        sql = (
            self._CATEGORY_SELECT
            + " WHERE c.id = :category_id"
              " AND c.user_id = :user_id"
              " AND c.deleted_at IS NULL"
        )
        rows = self._data_api.execute(
            sql,
            {"category_id": category_id, "user_id": user_id},
        )
        return self._row(rows[0]) if rows else None

    def list_by_style(
        self,
        *,
        user_id: str,
        style_id: str,
        limit: int,
        offset: int,
    ) -> PaginatedResult[CategoryRow]:
        sql = (
            self._CATEGORY_SELECT
            + " WHERE c.user_id = :user_id"
              " AND c.style_id = :style_id"
              " AND c.deleted_at IS NULL"
              " ORDER BY c.position ASC, c.created_at DESC, c.id ASC"
              " LIMIT :limit OFFSET :offset"
        )
        rows = self._data_api.execute(
            sql,
            {
                "user_id": user_id,
                "style_id": style_id,
                "limit": limit,
                "offset": offset,
            },
        )
        total_rows = self._data_api.execute(
            """
            SELECT COUNT(*) AS total
            FROM categories
            WHERE user_id = :user_id
              AND style_id = :style_id
              AND deleted_at IS NULL
            """,
            {"user_id": user_id, "style_id": style_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        return PaginatedResult(
            items=[self._row(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def list_all(
        self, *, user_id: str, limit: int, offset: int
    ) -> PaginatedResult[CategoryRow]:
        sql = (
            self._CATEGORY_SELECT
            + " WHERE c.user_id = :user_id"
              " AND c.deleted_at IS NULL"
              " ORDER BY c.created_at DESC, c.id ASC"
              " LIMIT :limit OFFSET :offset"
        )
        rows = self._data_api.execute(
            sql,
            {"user_id": user_id, "limit": limit, "offset": offset},
        )
        total_rows = self._data_api.execute(
            """
            SELECT COUNT(*) AS total
            FROM categories
            WHERE user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"user_id": user_id},
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        return PaginatedResult(
            items=[self._row(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
```

- [ ] **Step 7.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 10 tests PASS.

- [ ] **Step 7.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add get/list-by-style/list-all repository methods"
```

---

## Task 8: Repository — `rename`, `soft_delete`

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 8.1: Append failing tests**

```python
# Append to tests/unit/test_categories_repository.py

def test_rename_updates_and_returns_row() -> None:
    repo, data_api = _make()
    # First execute is the UPDATE ... RETURNING; second is the SELECT for shape.
    data_api.execute.side_effect = [
        [{"id": "c1"}],  # UPDATE returning at least one row -> success
        [
            {
                "id": "c1", "user_id": "u1", "style_id": "s1",
                "style_name": "House", "name": "Deep",
                "normalized_name": "deep", "position": 0,
                "track_count": 0,
                "created_at": "x", "updated_at": "x",
            }
        ],
    ]
    row = repo.rename(
        user_id="u1",
        category_id="c1",
        name="Deep",
        normalized_name="deep",
        now=_now(),
    )
    assert row.name == "Deep"
    update_sql = data_api.execute.call_args_list[0].args[0]
    assert "UPDATE categories" in update_sql
    assert "deleted_at IS NULL" in update_sql


def test_rename_raises_not_found_when_no_row() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.rename(
            user_id="u1", category_id="missing",
            name="x", normalized_name="x", now=_now(),
        )
    assert exc.value.error_code == "category_not_found"


def test_rename_maps_unique_violation_to_name_conflict() -> None:
    repo, data_api = _make()

    class FakeUniqueViolation(Exception):
        def __str__(self) -> str:
            return (
                "duplicate key value violates unique constraint "
                "\"uq_categories_user_style_normname\""
            )

    data_api.execute.side_effect = [FakeUniqueViolation()]
    with pytest.raises(NameConflictError):
        repo.rename(
            user_id="u1", category_id="c1",
            name="x", normalized_name="x", now=_now(),
        )


def test_soft_delete_updates_deleted_at() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"id": "c1"}]
    deleted = repo.soft_delete(
        user_id="u1", category_id="c1", now=_now()
    )
    assert deleted is True
    sql = data_api.execute.call_args.args[0]
    assert "UPDATE categories" in sql
    assert "deleted_at = :now" in sql
    assert "deleted_at IS NULL" in sql


def test_soft_delete_returns_false_when_no_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    deleted = repo.soft_delete(
        user_id="u1", category_id="missing", now=_now()
    )
    assert deleted is False
```

- [ ] **Step 8.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 5 new tests fail.

- [ ] **Step 8.3: Implement methods**

Add to `CategoriesRepository`:

```python
    def rename(
        self,
        *,
        user_id: str,
        category_id: str,
        name: str,
        normalized_name: str,
        now,
    ) -> CategoryRow:
        try:
            updated = self._data_api.execute(
                """
                UPDATE categories
                SET name = :name,
                    normalized_name = :normalized_name,
                    updated_at = :now
                WHERE id = :category_id
                  AND user_id = :user_id
                  AND deleted_at IS NULL
                RETURNING id
                """,
                {
                    "category_id": category_id,
                    "user_id": user_id,
                    "name": name,
                    "normalized_name": normalized_name,
                    "now": now,
                },
            )
        except Exception as exc:
            if "uq_categories_user_style_normname" in str(exc):
                raise NameConflictError(
                    "Category name already exists in this style"
                ) from exc
            raise

        if not updated:
            raise NotFoundError(
                "category_not_found", "Category not found"
            )

        row = self.get(user_id=user_id, category_id=category_id)
        if row is None:
            # Race: another caller deleted it between UPDATE and SELECT.
            raise NotFoundError(
                "category_not_found", "Category not found"
            )
        return row

    def soft_delete(
        self, *, user_id: str, category_id: str, now
    ) -> bool:
        rows = self._data_api.execute(
            """
            UPDATE categories
            SET deleted_at = :now,
                updated_at = :now
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "category_id": category_id,
                "user_id": user_id,
                "now": now,
            },
        )
        return bool(rows)
```

- [ ] **Step 8.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 15 tests PASS.

- [ ] **Step 8.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add categories rename and soft-delete"
```

---

## Task 9: Repository — `reorder`

`reorder` is transactional: SELECT current alive ids, validate set equality (delegated to service helper), UPDATE each row's position with the array index.

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 9.1: Append failing tests**

```python
# Append to tests/unit/test_categories_repository.py

def test_reorder_validates_set_and_updates_positions() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    # First execute: SELECT current alive ids -> three rows
    # N execute calls: UPDATE per id (3 here)
    # Last call: SELECT updated rows with full shape (list_by_style equivalent)
    data_api.execute.side_effect = [
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        [{"id": "c"}],
        [{"id": "a"}],
        [{"id": "b"}],
        [
            {"id": "c", "user_id": "u1", "style_id": "s1",
             "style_name": "House", "name": "C", "normalized_name": "c",
             "position": 0, "track_count": 0,
             "created_at": "x", "updated_at": "x"},
            {"id": "a", "user_id": "u1", "style_id": "s1",
             "style_name": "House", "name": "A", "normalized_name": "a",
             "position": 1, "track_count": 0,
             "created_at": "x", "updated_at": "x"},
            {"id": "b", "user_id": "u1", "style_id": "s1",
             "style_name": "House", "name": "B", "normalized_name": "b",
             "position": 2, "track_count": 0,
             "created_at": "x", "updated_at": "x"},
        ],
    ]
    result = repo.reorder(
        user_id="u1",
        style_id="s1",
        ordered_ids=["c", "a", "b"],
        now=_now(),
    )
    assert [r.id for r in result] == ["c", "a", "b"]
    select_sql = data_api.execute.call_args_list[0].args[0]
    assert "SELECT id FROM categories" in select_sql
    assert "deleted_at IS NULL" in select_sql
    update_sql = data_api.execute.call_args_list[1].args[0]
    assert "UPDATE categories" in update_sql
    assert "SET position = :position" in update_sql


def test_reorder_raises_when_style_missing() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    # We rely on a separate style-existence query first.
    # First call: style lookup -> empty
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.reorder(
            user_id="u1",
            style_id="missing",
            ordered_ids=[],
            now=_now(),
        )
    assert exc.value.error_code == "style_not_found"


def test_reorder_raises_order_mismatch_on_extra_id() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],   # style lookup
        [{"id": "a"}, {"id": "b"}],         # current set
    ]
    with pytest.raises(OrderMismatchError):
        repo.reorder(
            user_id="u1", style_id="s1",
            ordered_ids=["a", "b", "c"], now=_now(),
        )
```

- [ ] **Step 9.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 3 new tests fail.

- [ ] **Step 9.3: Implement `reorder`**

Add to `CategoriesRepository` (and import the service helper at the top):

```python
# At the top of categories_repository.py:
from .categories_service import validate_reorder_set
```

```python
    def reorder(
        self,
        *,
        user_id: str,
        style_id: str,
        ordered_ids: Sequence[str],
        now,
    ) -> list[CategoryRow]:
        with self._data_api.transaction() as tx_id:
            style_rows = self._data_api.execute(
                "SELECT id FROM clouder_styles WHERE id = :style_id",
                {"style_id": style_id},
                transaction_id=tx_id,
            )
            if not style_rows:
                raise NotFoundError("style_not_found", "Style not found")

            current_rows = self._data_api.execute(
                """
                SELECT id FROM categories
                WHERE user_id = :user_id
                  AND style_id = :style_id
                  AND deleted_at IS NULL
                """,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            actual_ids = {r["id"] for r in current_rows}
            validate_reorder_set(actual=actual_ids, requested=ordered_ids)

            for idx, cid in enumerate(ordered_ids):
                self._data_api.execute(
                    """
                    UPDATE categories
                    SET position = :position,
                        updated_at = :now
                    WHERE id = :category_id
                      AND user_id = :user_id
                      AND style_id = :style_id
                      AND deleted_at IS NULL
                    RETURNING id
                    """,
                    {
                        "position": idx,
                        "now": now,
                        "category_id": cid,
                        "user_id": user_id,
                        "style_id": style_id,
                    },
                    transaction_id=tx_id,
                )

            # Re-select with full shape, ordered.
            sql = (
                self._CATEGORY_SELECT
                + " WHERE c.user_id = :user_id"
                  " AND c.style_id = :style_id"
                  " AND c.deleted_at IS NULL"
                  " ORDER BY c.position ASC, c.created_at DESC, c.id ASC"
            )
            rows = self._data_api.execute(
                sql,
                {"user_id": user_id, "style_id": style_id},
                transaction_id=tx_id,
            )
            return [self._row(r) for r in rows]
```

- [ ] **Step 9.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 18 tests PASS.

- [ ] **Step 9.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add categories reorder"
```

---

## Task 10: Repository — `add_tracks_bulk` (heart of insert path)

This is the public method spec-D will reuse. Single-track HTTP add will wrap it in T11.

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 10.1: Append failing tests**

```python
# Append to tests/unit/test_categories_repository.py

def test_add_tracks_bulk_validates_category_ownership() -> None:
    repo, data_api = _make()
    # Category lookup returns empty -> not_found
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.add_tracks_bulk(
            user_id="u1",
            category_id="c1",
            items=[("t1", None)],
            now=_now(),
        )
    assert exc.value.error_code == "category_not_found"


def test_add_tracks_bulk_inserts_and_returns_count() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],            # category exists
        [{"id": "t1"}, {"id": "t2"}],  # track existence
        [{"track_id": "t1"}, {"track_id": "t2"}],  # INSERT ON CONFLICT RETURNING
    ]
    inserted = repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", None), ("t2", "block-1")],
        now=_now(),
    )
    assert inserted == 2
    insert_sql = data_api.execute.call_args_list[2].args[0]
    assert "INSERT INTO category_tracks" in insert_sql
    assert "ON CONFLICT (category_id, track_id) DO NOTHING" in insert_sql


def test_add_tracks_bulk_raises_track_not_found() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],       # category exists
        [{"id": "t1"}],       # only one of the requested tracks exists
    ]
    with pytest.raises(NotFoundError) as exc:
        repo.add_tracks_bulk(
            user_id="u1", category_id="c1",
            items=[("t1", None), ("t-missing", None)], now=_now(),
        )
    assert exc.value.error_code == "track_not_found"


def test_add_tracks_bulk_passes_transaction_id() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"id": "t1"}],
        [{"track_id": "t1"}],
    ]
    repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", "block-1")],
        now=_now(),
        transaction_id="external-tx",
    )
    for call in data_api.execute.call_args_list:
        assert call.kwargs.get("transaction_id") == "external-tx"


def test_add_tracks_bulk_idempotent_returns_zero_when_all_existing() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"id": "t1"}],
        [],  # ON CONFLICT DO NOTHING -> RETURNING is empty
    ]
    inserted = repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", None)],
        now=_now(),
    )
    assert inserted == 0
```

- [ ] **Step 10.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 5 new tests fail.

- [ ] **Step 10.3: Implement `add_tracks_bulk`**

Add to `CategoriesRepository`:

```python
    def add_tracks_bulk(
        self,
        *,
        user_id: str,
        category_id: str,
        items: Sequence[tuple[str, str | None]],
        now,
        transaction_id: str | None = None,
    ) -> int:
        """Insert (track, source_triage_block_id) pairs idempotently.

        Used by both the single-track HTTP path and spec-D's triage finalize.
        When called inside an existing transaction (spec-D), pass `transaction_id`
        so reads see in-flight writes (CLAUDE.md note on Aurora Data API).

        Returns the count of rows actually inserted (excludes existing).
        Raises NotFoundError("category_not_found" or "track_not_found").
        """
        cat_rows = self._data_api.execute(
            """
            SELECT id FROM categories
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"category_id": category_id, "user_id": user_id},
            transaction_id=transaction_id,
        )
        if not cat_rows:
            raise NotFoundError("category_not_found", "Category not found")

        if not items:
            return 0

        track_ids = list({tid for tid, _ in items})
        # Build an IN-list parametrically (Data API forbids ANY/array on plain strings).
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {f"t{i}": tid for i, tid in enumerate(track_ids)}
        existing = self._data_api.execute(
            f"SELECT id FROM clouder_tracks WHERE id IN ({placeholders})",
            params,
            transaction_id=transaction_id,
        )
        existing_ids = {r["id"] for r in existing}
        missing = [tid for tid in track_ids if tid not in existing_ids]
        if missing:
            raise NotFoundError(
                "track_not_found", f"Track(s) not found: {missing[0]}"
            )

        # Build a multi-row INSERT.
        value_rows = []
        params = {
            "category_id": category_id,
            "now": now,
        }
        for i, (tid, src) in enumerate(items):
            value_rows.append(
                f"(:category_id, :tid_{i}, :now, :src_{i})"
            )
            params[f"tid_{i}"] = tid
            params[f"src_{i}"] = src
        sql = f"""
            INSERT INTO category_tracks (
                category_id, track_id, added_at, source_triage_block_id
            ) VALUES {", ".join(value_rows)}
            ON CONFLICT (category_id, track_id) DO NOTHING
            RETURNING track_id
        """
        rows = self._data_api.execute(
            sql, params, transaction_id=transaction_id
        )
        return len(rows)
```

- [ ] **Step 10.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 23 tests PASS.

- [ ] **Step 10.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add idempotent add_tracks_bulk for spec-D contract"
```

---

## Task 11: Repository — `add_track` (single-row wrapper) and `remove_track`

`add_track` calls `add_tracks_bulk` with one item. It must distinguish "newly added" from "already present" — when bulk returns 0, fetch the existing row and return its `added_at` and `source_triage_block_id`.

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 11.1: Append failing tests**

```python
# Append to tests/unit/test_categories_repository.py

def test_add_track_returns_added_when_newly_inserted() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],            # category lookup
        [{"id": "t1"}],            # track lookup
        [{"track_id": "t1"}],       # INSERT returning -> newly inserted
    ]
    result, was_new = repo.add_track(
        user_id="u1",
        category_id="c1",
        track_id="t1",
        source_triage_block_id=None,
        now=_now(),
    )
    assert was_new is True
    assert result["added_at"] is not None
    assert result["source_triage_block_id"] is None


def test_add_track_returns_existing_when_already_present() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"id": "t1"}],
        [],   # ON CONFLICT DO NOTHING -> empty
        [
            {
                "added_at": "2026-04-01T00:00:00Z",
                "source_triage_block_id": "tb-1",
            }
        ],
    ]
    result, was_new = repo.add_track(
        user_id="u1",
        category_id="c1",
        track_id="t1",
        source_triage_block_id=None,
        now=_now(),
    )
    assert was_new is False
    assert result["added_at"] == "2026-04-01T00:00:00Z"
    assert result["source_triage_block_id"] == "tb-1"


def test_remove_track_returns_true_on_delete() -> None:
    repo, data_api = _make()
    # Validate category ownership first (one execute), then delete
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"track_id": "t1"}],   # DELETE RETURNING
    ]
    deleted = repo.remove_track(
        user_id="u1", category_id="c1", track_id="t1"
    )
    assert deleted is True
    delete_sql = data_api.execute.call_args_list[1].args[0]
    assert "DELETE FROM category_tracks" in delete_sql


def test_remove_track_raises_category_not_found() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.remove_track(
            user_id="u1", category_id="missing", track_id="t1"
        )
    assert exc.value.error_code == "category_not_found"


def test_remove_track_returns_false_when_not_in_category() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [],   # DELETE RETURNING -> empty
    ]
    deleted = repo.remove_track(
        user_id="u1", category_id="c1", track_id="t-missing"
    )
    assert deleted is False
```

- [ ] **Step 11.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 5 new tests fail.

- [ ] **Step 11.3: Implement methods**

Add to `CategoriesRepository`:

```python
    def add_track(
        self,
        *,
        user_id: str,
        category_id: str,
        track_id: str,
        source_triage_block_id: str | None,
        now,
    ) -> tuple[Mapping[str, Any], bool]:
        """Add one track to a category. Idempotent on (category_id, track_id).

        Returns ({added_at, source_triage_block_id}, was_newly_added).
        """
        inserted = self.add_tracks_bulk(
            user_id=user_id,
            category_id=category_id,
            items=[(track_id, source_triage_block_id)],
            now=now,
        )
        if inserted:
            return (
                {
                    "added_at": now.isoformat(),
                    "source_triage_block_id": source_triage_block_id,
                },
                True,
            )

        rows = self._data_api.execute(
            """
            SELECT added_at, source_triage_block_id
            FROM category_tracks
            WHERE category_id = :category_id
              AND track_id = :track_id
            """,
            {"category_id": category_id, "track_id": track_id},
        )
        row = rows[0]
        return (
            {
                "added_at": str(row["added_at"]),
                "source_triage_block_id": row["source_triage_block_id"],
            },
            False,
        )

    def remove_track(
        self, *, user_id: str, category_id: str, track_id: str
    ) -> bool:
        cat_rows = self._data_api.execute(
            """
            SELECT id FROM categories
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"category_id": category_id, "user_id": user_id},
        )
        if not cat_rows:
            raise NotFoundError("category_not_found", "Category not found")

        rows = self._data_api.execute(
            """
            DELETE FROM category_tracks
            WHERE category_id = :category_id
              AND track_id = :track_id
            RETURNING track_id
            """,
            {"category_id": category_id, "track_id": track_id},
        )
        return bool(rows)
```

- [ ] **Step 11.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 28 tests PASS.

- [ ] **Step 11.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add single-track add/remove wrappers"
```

---

## Task 12: Repository — `list_tracks` (paginated tracks in a category)

JOINs `category_tracks → clouder_tracks → clouder_track_artists → clouder_artists`. Returns full track shape plus `added_at` and `source_triage_block_id`. Supports optional `search` (lowercase-trimmed before ILIKE).

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 12.1: Append failing tests**

```python
# Append to tests/unit/test_categories_repository.py

def test_list_tracks_validates_category() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.list_tracks(
            user_id="u1", category_id="missing",
            limit=50, offset=0, search=None,
        )
    assert exc.value.error_code == "category_not_found"


def test_list_tracks_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [
            {
                "id": "t1", "title": "Song", "mix_name": None,
                "isrc": "X", "bpm": 124, "length_ms": 360000,
                "publish_date": None, "spotify_id": None,
                "release_type": "single", "is_ai_suspected": False,
                "artist_names": "Artist A,Artist B",
                "added_at": "2026-04-27T12:00:00Z",
                "source_triage_block_id": None,
            }
        ],
        [{"total": 1}],
    ]
    result = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
    )
    assert result.total == 1
    item = result.items[0]
    assert item.track["id"] == "t1"
    assert item.track["artists"] == ["Artist A", "Artist B"]
    assert item.added_at == "2026-04-27T12:00:00Z"
    assert item.source_triage_block_id is None


def test_list_tracks_applies_search_lowercased() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [],
        [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search="  Tech  ",
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    list_params = data_api.execute.call_args_list[1].args[1]
    assert "ILIKE" in list_sql
    assert list_params["search"] == "%tech%"
```

- [ ] **Step 12.2: Run to verify failure**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 3 new tests fail.

- [ ] **Step 12.3: Implement `list_tracks`**

Add to `CategoriesRepository`:

```python
    def list_tracks(
        self,
        *,
        user_id: str,
        category_id: str,
        limit: int,
        offset: int,
        search: str | None,
    ) -> PaginatedResult[TrackInCategoryRow]:
        cat_rows = self._data_api.execute(
            """
            SELECT id FROM categories
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"category_id": category_id, "user_id": user_id},
        )
        if not cat_rows:
            raise NotFoundError("category_not_found", "Category not found")

        params: dict[str, Any] = {
            "category_id": category_id,
            "limit": limit,
            "offset": offset,
        }
        search_clause = ""
        if search and search.strip():
            search_clause = " AND t.normalized_title ILIKE :search "
            params["search"] = f"%{search.strip().lower()}%"

        sql = f"""
            SELECT
                t.id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                t.publish_date, t.spotify_id, t.release_type, t.is_ai_suspected,
                STRING_AGG(a.name, ',' ORDER BY cta.role, a.name) AS artist_names,
                ct.added_at, ct.source_triage_block_id
            FROM category_tracks ct
            JOIN clouder_tracks t ON t.id = ct.track_id
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists a ON a.id = cta.artist_id
            WHERE ct.category_id = :category_id
              {search_clause}
            GROUP BY t.id, ct.added_at, ct.source_triage_block_id
            ORDER BY ct.added_at DESC, t.id ASC
            LIMIT :limit OFFSET :offset
        """
        rows = self._data_api.execute(sql, params)

        count_params = {"category_id": category_id}
        count_clause = ""
        if "search" in params:
            count_clause = " AND t.normalized_title ILIKE :search "
            count_params["search"] = params["search"]
        total_rows = self._data_api.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM category_tracks ct
            JOIN clouder_tracks t ON t.id = ct.track_id
            WHERE ct.category_id = :category_id
              {count_clause}
            """,
            count_params,
        )
        total = int(total_rows[0]["total"]) if total_rows else 0

        items = []
        for r in rows:
            artists_raw = r.pop("artist_names")
            track = dict(r)
            track["artists"] = (
                [n.strip() for n in artists_raw.split(",")] if artists_raw else []
            )
            added_at = track.pop("added_at")
            source_id = track.pop("source_triage_block_id")
            items.append(
                TrackInCategoryRow(
                    track=track,
                    added_at=str(added_at),
                    source_triage_block_id=source_id,
                )
            )
        return PaginatedResult(items=items, total=total, limit=limit, offset=offset)
```

- [ ] **Step 12.4: Run to verify pass**

Run: `pytest tests/unit/test_categories_repository.py -v`
Expected: 31 tests PASS.

- [ ] **Step 12.5: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): add list-tracks repository method"
```

---

## Task 13: Lambda skeleton — routing, auth, error envelope, correlation id

`curation_handler.py` is the new Lambda entry point. It owns routing for spec-C (and later spec-D/E). Each route handler reads `user_id` from the authorizer context, calls a repository method, and maps domain errors to the existing `{error_code, message, correlation_id}` envelope.

**Files:**
- Create: `src/collector/curation_handler.py`
- Test: `tests/integration/test_curation_handler.py` (integration-style with FakeRepo)

- [ ] **Step 13.1: Set up the integration test fixture and a route-not-found smoke test**

```python
# tests/integration/test_curation_handler.py
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from collector.curation import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
    PaginatedResult,
    ValidationError,
)
from collector.curation.categories_repository import (
    CategoryRow,
    TrackInCategoryRow,
)
from collector.curation_handler import lambda_handler


# ---------- Fake repository --------------------------------------------------

class FakeRepo:
    """In-memory CategoriesRepository for integration tests."""

    def __init__(self) -> None:
        # category_id -> dict
        self.categories: dict[str, dict] = {}
        # (category_id, track_id) -> dict
        self.tracks: dict[tuple[str, str], dict] = {}
        # style_id -> name
        self.styles: dict[str, str] = {"s1": "House", "s2": "Techno"}
        # track id -> dict
        self.track_meta: dict[str, dict] = {}

    def _row(self, c: dict) -> CategoryRow:
        track_count = sum(
            1 for (cid, _) in self.tracks if cid == c["id"]
        )
        return CategoryRow(
            id=c["id"], user_id=c["user_id"], style_id=c["style_id"],
            style_name=self.styles[c["style_id"]],
            name=c["name"], normalized_name=c["normalized_name"],
            position=c["position"], track_count=track_count,
            created_at=c["created_at"], updated_at=c["updated_at"],
        )

    def create(self, *, user_id, style_id, category_id, name, normalized_name, now):
        if style_id not in self.styles:
            raise NotFoundError("style_not_found", "Style not found")
        for c in self.categories.values():
            if (
                c["user_id"] == user_id
                and c["style_id"] == style_id
                and c["normalized_name"] == normalized_name
                and c.get("deleted_at") is None
            ):
                raise NameConflictError("Name exists")
        positions = [
            c["position"] for c in self.categories.values()
            if c["user_id"] == user_id
            and c["style_id"] == style_id
            and c.get("deleted_at") is None
        ]
        new_pos = (max(positions) + 1) if positions else 0
        c = {
            "id": category_id, "user_id": user_id, "style_id": style_id,
            "name": name, "normalized_name": normalized_name,
            "position": new_pos,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
            "deleted_at": None,
        }
        self.categories[category_id] = c
        return self._row(c)

    def get(self, *, user_id, category_id):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            return None
        return self._row(c)

    def list_by_style(self, *, user_id, style_id, limit, offset):
        if style_id not in self.styles:
            raise NotFoundError("style_not_found", "Style not found")
        items = [
            self._row(c) for c in self.categories.values()
            if c["user_id"] == user_id
            and c["style_id"] == style_id
            and c.get("deleted_at") is None
        ]
        items.sort(key=lambda r: (r.position, r.created_at))
        total = len(items)
        return PaginatedResult(
            items=items[offset:offset+limit], total=total,
            limit=limit, offset=offset,
        )

    def list_all(self, *, user_id, limit, offset):
        items = [
            self._row(c) for c in self.categories.values()
            if c["user_id"] == user_id and c.get("deleted_at") is None
        ]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        return PaginatedResult(
            items=items[offset:offset+limit], total=total,
            limit=limit, offset=offset,
        )

    def rename(self, *, user_id, category_id, name, normalized_name, now):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        for other in self.categories.values():
            if (
                other["id"] != category_id
                and other["user_id"] == user_id
                and other["style_id"] == c["style_id"]
                and other["normalized_name"] == normalized_name
                and other.get("deleted_at") is None
            ):
                raise NameConflictError("Name exists")
        c["name"] = name
        c["normalized_name"] = normalized_name
        c["updated_at"] = now.isoformat()
        return self._row(c)

    def soft_delete(self, *, user_id, category_id, now):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            return False
        c["deleted_at"] = now.isoformat()
        c["updated_at"] = now.isoformat()
        return True

    def reorder(self, *, user_id, style_id, ordered_ids, now):
        if style_id not in self.styles:
            raise NotFoundError("style_not_found", "Style not found")
        actual = {
            c["id"] for c in self.categories.values()
            if c["user_id"] == user_id
            and c["style_id"] == style_id
            and c.get("deleted_at") is None
        }
        if set(ordered_ids) != actual or len(set(ordered_ids)) != len(ordered_ids):
            raise OrderMismatchError("mismatch")
        for idx, cid in enumerate(ordered_ids):
            self.categories[cid]["position"] = idx
            self.categories[cid]["updated_at"] = now.isoformat()
        return [
            self._row(self.categories[cid]) for cid in ordered_ids
        ]

    def add_tracks_bulk(
        self, *, user_id, category_id, items, now, transaction_id=None
    ):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        for tid, _ in items:
            if tid not in self.track_meta:
                raise NotFoundError("track_not_found", f"Track {tid}")
        added = 0
        for tid, src in items:
            key = (category_id, tid)
            if key in self.tracks:
                continue
            self.tracks[key] = {
                "added_at": now.isoformat(),
                "source_triage_block_id": src,
            }
            added += 1
        return added

    def add_track(
        self, *, user_id, category_id, track_id, source_triage_block_id, now
    ):
        added = self.add_tracks_bulk(
            user_id=user_id, category_id=category_id,
            items=[(track_id, source_triage_block_id)], now=now,
        )
        existing = self.tracks[(category_id, track_id)]
        return (
            {
                "added_at": existing["added_at"],
                "source_triage_block_id": existing["source_triage_block_id"],
            },
            bool(added),
        )

    def remove_track(self, *, user_id, category_id, track_id):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        return self.tracks.pop((category_id, track_id), None) is not None

    def list_tracks(
        self, *, user_id, category_id, limit, offset, search
    ):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        rows = []
        for (cid, tid), meta in self.tracks.items():
            if cid != category_id:
                continue
            track = self.track_meta[tid]
            if search and search.strip().lower() not in track.get(
                "normalized_title", ""
            ):
                continue
            rows.append(
                TrackInCategoryRow(
                    track=track,
                    added_at=meta["added_at"],
                    source_triage_block_id=meta["source_triage_block_id"],
                )
            )
        rows.sort(key=lambda r: (r.added_at, r.track["id"]), reverse=True)
        total = len(rows)
        return PaginatedResult(
            items=rows[offset:offset+limit],
            total=total, limit=limit, offset=offset,
        )


# ---------- Test helpers -----------------------------------------------------

@pytest.fixture
def context() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="lambda-req-1")


@pytest.fixture
def fake_repo(monkeypatch) -> FakeRepo:
    repo = FakeRepo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: repo,
    )
    return repo


def _event(
    *,
    method: str,
    route: str,
    user_id: str = "u1",
    is_admin: bool = False,
    path_params: Mapping[str, str] | None = None,
    query: Mapping[str, str] | None = None,
    body: Any | None = None,
    correlation_id: str = "cid-1",
) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-1",
            "routeKey": f"{method} {route}",
            "authorizer": {
                "lambda": {
                    "user_id": user_id, "session_id": "s",
                    "is_admin": is_admin,
                }
            },
        },
        "headers": {"x-correlation-id": correlation_id},
        "pathParameters": dict(path_params) if path_params else None,
        "queryStringParameters": dict(query) if query else None,
        "body": json.dumps(body) if body is not None else None,
    }


def _read(resp: dict) -> tuple[int, dict]:
    return resp["statusCode"], json.loads(resp["body"])


# ---------- Skeleton smoke tests --------------------------------------------

def test_unknown_route_returns_404(fake_repo, context):
    resp = lambda_handler(
        _event(method="GET", route="/nonexistent"), context
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "not_found"


def test_missing_authorizer_returns_401(fake_repo, context):
    event = _event(method="GET", route="/categories")
    event["requestContext"].pop("authorizer", None)
    resp = lambda_handler(event, context)
    status, body = _read(resp)
    assert status == 401
    assert body["error_code"] == "unauthorized"
```

- [ ] **Step 13.2: Run to verify failure**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: ImportError on `collector.curation_handler`.

- [ ] **Step 13.3: Implement the Lambda skeleton**

```python
# src/collector/curation_handler.py
"""Lambda handler for the user-curation surface (spec-C/D/E).

Routes for spec-C only at this revision. spec-D and spec-E will append
to `_ROUTE_TABLE`. Every route is JWT-gated by the API Gateway Lambda
Authorizer (spec-A); `user_id` is read from
`event.requestContext.authorizer.lambda.user_id`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from pydantic import ValidationError as PydanticValidationError

from .curation import (
    CurationError,
    NotFoundError,
    PaginatedResult,
    ValidationError,
    utc_now,
)
from .curation.categories_repository import (
    CategoriesRepository,
    create_default_categories_repository,
)
from .logging_utils import log_event


def _extract_correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers")
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "x-correlation-id":
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return str(uuid.uuid4())


def _json_response(
    status_code: int,
    payload: Mapping[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(payload),
    }


def _error(
    status: int, error_code: str, message: str, correlation_id: str
) -> dict[str, Any]:
    return _json_response(
        status,
        {
            "error_code": error_code,
            "message": message,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _user_id_or_none(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authz = rc.get("authorizer")
        if isinstance(authz, Mapping):
            ctx = authz.get("lambda")
            if isinstance(ctx, Mapping):
                uid = ctx.get("user_id")
                if isinstance(uid, str) and uid:
                    return uid
    return None


def _parse_body(event: Mapping[str, Any]) -> Mapping[str, Any]:
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON body: {exc}") from exc
    if isinstance(body, Mapping):
        return body
    raise ValidationError("Invalid body type")


def _parse_pagination(event: Mapping[str, Any]) -> tuple[int, int]:
    qp = event.get("queryStringParameters") or {}
    raw_limit = qp.get("limit", "50")
    raw_offset = qp.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ValidationError("offset must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    return limit, offset


def _category_response(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "position": row.position,
        "track_count": row.track_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# ---------- Routing ---------------------------------------------------------

def lambda_handler(
    event: Mapping[str, Any], context: Any
) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)

    user_id = _user_id_or_none(event)
    if user_id is None:
        return _error(401, "unauthorized", "Missing authorizer context", correlation_id)

    rc = event.get("requestContext") or {}
    route_key = rc.get("routeKey") if isinstance(rc, Mapping) else None
    if not isinstance(route_key, str):
        return _error(404, "not_found", "Unknown route", correlation_id)

    handler = _ROUTE_TABLE.get(route_key)
    if handler is None:
        return _error(404, "not_found", "Unknown route", correlation_id)

    repo = create_default_categories_repository()
    if repo is None:
        return _error(503, "db_not_configured", "Database not configured", correlation_id)

    try:
        return handler(event, repo, user_id, correlation_id)
    except PydanticValidationError as exc:
        return _error(422, "validation_error", str(exc.errors()[0]["msg"]), correlation_id)
    except CurationError as exc:
        return _error(exc.http_status, exc.error_code, exc.message, correlation_id)
    except Exception as exc:  # noqa: BLE001
        log_event(
            "ERROR",
            "curation_handler_unhandled",
            correlation_id=correlation_id,
            user_id=user_id,
            error=str(exc),
        )
        return _error(500, "internal_error", "Internal error", correlation_id)


# ---------- Route handlers (Tasks 14–22 fill in) ----------------------------

# Each takes (event, repo, user_id, correlation_id) and returns a Lambda response dict.
_ROUTE_TABLE: dict[str, Callable[..., dict[str, Any]]] = {}
```

- [ ] **Step 13.4: Run to verify pass**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 2 tests PASS.

- [ ] **Step 13.5: Commit**

```bash
git add src/collector/curation_handler.py tests/integration/test_curation_handler.py
git commit -m "feat(curation): add Lambda skeleton with auth + error envelope"
```

---

## Task 14: Handler — `POST /styles/{style_id}/categories`

**Files:**
- Modify: `src/collector/curation_handler.py`
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 14.1: Append failing tests**

```python
# Append to tests/integration/test_curation_handler.py

def test_create_category_201(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "Tech House"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["name"] == "Tech House"
    assert body["style_name"] == "House"
    assert body["position"] == 0
    assert body["track_count"] == 0


def test_create_category_409_on_duplicate(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "tech"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 409
    assert body["error_code"] == "name_conflict"


def test_create_category_404_style(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "missing"},
            body={"name": "Tech"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "style_not_found"


def test_create_category_422_empty_name(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "   "},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "validation_error"
```

Add to imports at top of the test file:
```python
from datetime import datetime, timezone
```

- [ ] **Step 14.2: Run to verify failure**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 4 new tests fail.

- [ ] **Step 14.3: Implement create handler**

Add to `curation_handler.py`:

```python
from .curation.categories_service import (
    normalize_category_name,
    validate_category_name,
)
from .curation.schemas import CreateCategoryIn


def _handle_create_category(
    event, repo: CategoriesRepository, user_id: str, correlation_id: str
):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    body = CreateCategoryIn.model_validate(_parse_body(event))
    validate_category_name(body.name)
    normalized = normalize_category_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    category_id = str(uuid.uuid4())
    now = utc_now()
    row = repo.create(
        user_id=user_id,
        style_id=style_id,
        category_id=category_id,
        name=body.name.strip(),
        normalized_name=normalized,
        now=now,
    )
    log_event(
        "INFO",
        "category_created",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=row.id,
        style_id=row.style_id,
    )
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(201, payload, correlation_id)


_ROUTE_TABLE["POST /styles/{style_id}/categories"] = _handle_create_category
```

- [ ] **Step 14.4: Run to verify pass**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 6 tests PASS.

- [ ] **Step 14.5: Commit**

```bash
git add src/collector/curation_handler.py tests/integration/test_curation_handler.py
git commit -m "feat(curation): add POST /styles/{style_id}/categories"
```

---

## Task 15: Handler — `GET /styles/{style_id}/categories` and `GET /categories`

**Files:**
- Modify: `src/collector/curation_handler.py`
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 15.1: Append failing tests**

```python
# Append to tests/integration/test_curation_handler.py

def test_list_by_style_returns_paginated(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    for i, name in enumerate(["A", "B", "C"]):
        fake_repo.create(
            user_id="u1", style_id="s1", category_id=f"c{i}",
            name=name, normalized_name=name.lower(), now=now,
        )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 3
    assert [it["name"] for it in body["items"]] == ["A", "B", "C"]
    assert [it["position"] for it in body["items"]] == [0, 1, 2]


def test_list_by_style_404_style_missing(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "missing"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "style_not_found"


def test_list_all_returns_cross_style(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="A", normalized_name="a", now=now,
    )
    fake_repo.create(
        user_id="u1", style_id="s2", category_id="c2",
        name="B", normalized_name="b", now=now,
    )
    resp = lambda_handler(
        _event(method="GET", route="/categories"),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 2
```

- [ ] **Step 15.2: Run to verify failure**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 3 new tests fail.

- [ ] **Step 15.3: Implement list handlers**

Add to `curation_handler.py`:

```python
def _handle_list_by_style(event, repo, user_id, correlation_id):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    limit, offset = _parse_pagination(event)
    result = repo.list_by_style(
        user_id=user_id, style_id=style_id, limit=limit, offset=offset,
    )
    return _json_response(
        200,
        {
            "items": [_category_response(r) for r in result.items],
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_list_all(event, repo, user_id, correlation_id):
    limit, offset = _parse_pagination(event)
    result = repo.list_all(user_id=user_id, limit=limit, offset=offset)
    return _json_response(
        200,
        {
            "items": [_category_response(r) for r in result.items],
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


_ROUTE_TABLE["GET /styles/{style_id}/categories"] = _handle_list_by_style
_ROUTE_TABLE["GET /categories"] = _handle_list_all
```

- [ ] **Step 15.4: Run to verify pass**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 9 tests PASS.

- [ ] **Step 15.5: Commit**

```bash
git add src/collector/curation_handler.py tests/integration/test_curation_handler.py
git commit -m "feat(curation): add list-by-style and cross-style list"
```

---

## Task 16: Handler — `GET /categories/{id}`, `PATCH /categories/{id}`, `DELETE /categories/{id}`

**Files:**
- Modify: `src/collector/curation_handler.py`
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 16.1: Append failing tests**

```python
# Append to tests/integration/test_curation_handler.py

def test_get_detail_200(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["id"] == "c1"


def test_get_detail_404(fake_repo, context):
    resp = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "missing"}),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "category_not_found"


def test_rename_200(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "c1"},
            body={"name": "Deep"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["name"] == "Deep"


def test_rename_409_on_conflict(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c2",
        name="Deep", normalized_name="deep", now=now,
    )
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "c1"},
            body={"name": "Deep"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 409


def test_delete_204(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(method="DELETE", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    assert resp["statusCode"] == 204
    assert resp["body"] in ("", "null")


def test_delete_404_already_gone(fake_repo, context):
    resp = lambda_handler(
        _event(method="DELETE", route="/categories/{id}", path_params={"id": "missing"}),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "category_not_found"
```

- [ ] **Step 16.2: Run to verify failure**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 6 new tests fail.

- [ ] **Step 16.3: Implement detail/rename/delete handlers**

Add to `curation_handler.py`:

```python
from .curation.schemas import RenameCategoryIn


def _handle_get_detail(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    row = repo.get(user_id=user_id, category_id=cid)
    if row is None:
        raise NotFoundError("category_not_found", "Category not found")
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_rename(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    body = RenameCategoryIn.model_validate(_parse_body(event))
    validate_category_name(body.name)
    normalized = normalize_category_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    row = repo.rename(
        user_id=user_id,
        category_id=cid,
        name=body.name.strip(),
        normalized_name=normalized,
        now=utc_now(),
    )
    log_event(
        "INFO",
        "category_renamed",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=row.id,
    )
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_soft_delete(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    deleted = repo.soft_delete(
        user_id=user_id, category_id=cid, now=utc_now()
    )
    if not deleted:
        raise NotFoundError("category_not_found", "Category not found")
    log_event(
        "INFO",
        "category_soft_deleted",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


_ROUTE_TABLE["GET /categories/{id}"] = _handle_get_detail
_ROUTE_TABLE["PATCH /categories/{id}"] = _handle_rename
_ROUTE_TABLE["DELETE /categories/{id}"] = _handle_soft_delete
```

- [ ] **Step 16.4: Run to verify pass**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 15 tests PASS.

- [ ] **Step 16.5: Commit**

```bash
git add src/collector/curation_handler.py tests/integration/test_curation_handler.py
git commit -m "feat(curation): add detail/rename/soft-delete routes"
```

---

## Task 17: Handler — `PUT /styles/{style_id}/categories/order`

**Files:**
- Modify: `src/collector/curation_handler.py`
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 17.1: Append failing tests**

```python
# Append to tests/integration/test_curation_handler.py

def test_reorder_200(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    for i, name in enumerate(["A", "B", "C"]):
        fake_repo.create(
            user_id="u1", style_id="s1", category_id=f"c{i}",
            name=name, normalized_name=name.lower(), now=now,
        )
    resp = lambda_handler(
        _event(
            method="PUT",
            route="/styles/{style_id}/categories/order",
            path_params={"style_id": "s1"},
            body={"category_ids": ["c2", "c0", "c1"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert [it["id"] for it in body["items"]] == ["c2", "c0", "c1"]
    assert [it["position"] for it in body["items"]] == [0, 1, 2]


def test_reorder_422_on_extra_id(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="A", normalized_name="a", now=now,
    )
    resp = lambda_handler(
        _event(
            method="PUT",
            route="/styles/{style_id}/categories/order",
            path_params={"style_id": "s1"},
            body={"category_ids": ["c1", "ghost"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "order_mismatch"


def test_reorder_404_style_missing(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="PUT",
            route="/styles/{style_id}/categories/order",
            path_params={"style_id": "missing"},
            body={"category_ids": []},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
```

- [ ] **Step 17.2: Run to verify failure**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 3 new tests fail.

- [ ] **Step 17.3: Implement reorder handler**

```python
from .curation.schemas import ReorderCategoriesIn


def _handle_reorder(event, repo, user_id, correlation_id):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    body = ReorderCategoriesIn.model_validate(_parse_body(event))
    rows = repo.reorder(
        user_id=user_id,
        style_id=style_id,
        ordered_ids=body.category_ids,
        now=utc_now(),
    )
    log_event(
        "INFO",
        "category_order_updated",
        correlation_id=correlation_id,
        user_id=user_id,
        style_id=style_id,
        size=len(rows),
    )
    return _json_response(
        200,
        {
            "items": [_category_response(r) for r in rows],
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


_ROUTE_TABLE["PUT /styles/{style_id}/categories/order"] = _handle_reorder
```

- [ ] **Step 17.4: Run to verify pass**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 18 tests PASS.

- [ ] **Step 17.5: Commit**

```bash
git add src/collector/curation_handler.py tests/integration/test_curation_handler.py
git commit -m "feat(curation): add reorder route with set-equality validation"
```

---

## Task 18: Handler — `GET /categories/{id}/tracks`, `POST /categories/{id}/tracks`, `DELETE /categories/{id}/tracks/{track_id}`

**Files:**
- Modify: `src/collector/curation_handler.py`
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 18.1: Append failing tests**

```python
# Append to tests/integration/test_curation_handler.py

def test_list_tracks_200(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {
        "id": "t1", "title": "Song", "normalized_title": "song",
        "artists": ["A"],
    }
    fake_repo.add_track(
        user_id="u1", category_id="c1", track_id="t1",
        source_triage_block_id=None, now=now,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == "t1"
    assert body["items"][0]["added_at"] is not None
    assert body["items"][0]["source_triage_block_id"] is None


def test_add_track_201(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {"id": "t1", "title": "X"}
    resp = lambda_handler(
        _event(
            method="POST",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            body={"track_id": "t1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["result"] == "added"
    assert body["source_triage_block_id"] is None


def test_add_track_200_already_present(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {"id": "t1"}
    fake_repo.add_track(
        user_id="u1", category_id="c1", track_id="t1",
        source_triage_block_id=None, now=now,
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            body={"track_id": "t1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["result"] == "already_present"


def test_add_track_404_track_missing(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            body={"track_id": "ghost"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "track_not_found"


def test_remove_track_204(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {"id": "t1"}
    fake_repo.add_track(
        user_id="u1", category_id="c1", track_id="t1",
        source_triage_block_id=None, now=now,
    )
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}/tracks/{track_id}",
            path_params={"id": "c1", "track_id": "t1"},
        ),
        context,
    )
    assert resp["statusCode"] == 204


def test_remove_track_404_when_not_in_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}/tracks/{track_id}",
            path_params={"id": "c1", "track_id": "ghost"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "track_not_in_category"
```

- [ ] **Step 18.2: Run to verify failure**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 6 new tests fail.

- [ ] **Step 18.3: Implement track-list / add / remove handlers**

```python
from .curation.schemas import AddTrackIn


def _track_in_category_response(item) -> dict[str, Any]:
    track = dict(item.track)
    track["added_at"] = item.added_at
    track["source_triage_block_id"] = item.source_triage_block_id
    return track


def _handle_list_tracks(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")
    result = repo.list_tracks(
        user_id=user_id, category_id=cid,
        limit=limit, offset=offset, search=search,
    )
    return _json_response(
        200,
        {
            "items": [_track_in_category_response(it) for it in result.items],
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_add_track(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    body = AddTrackIn.model_validate(_parse_body(event))
    result, was_new = repo.add_track(
        user_id=user_id, category_id=cid, track_id=body.track_id,
        source_triage_block_id=None, now=utc_now(),
    )
    log_event(
        "INFO",
        "category_track_added",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
        track_id=body.track_id,
        result="added" if was_new else "already_present",
    )
    payload = {
        "result": "added" if was_new else "already_present",
        "added_at": result["added_at"],
        "source_triage_block_id": result["source_triage_block_id"],
        "correlation_id": correlation_id,
    }
    return _json_response(201 if was_new else 200, payload, correlation_id)


def _handle_remove_track(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    cid = pp.get("id")
    tid = pp.get("track_id")
    if not cid or not tid:
        raise ValidationError("id and track_id are required in path")
    deleted = repo.remove_track(
        user_id=user_id, category_id=cid, track_id=tid,
    )
    if not deleted:
        raise NotFoundError("track_not_in_category", "Track not in category")
    log_event(
        "INFO",
        "category_track_removed",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
        track_id=tid,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


_ROUTE_TABLE["GET /categories/{id}/tracks"] = _handle_list_tracks
_ROUTE_TABLE["POST /categories/{id}/tracks"] = _handle_add_track
_ROUTE_TABLE["DELETE /categories/{id}/tracks/{track_id}"] = _handle_remove_track
```

- [ ] **Step 18.4: Run to verify pass**

Run: `pytest tests/integration/test_curation_handler.py -v`
Expected: 24 tests PASS.

- [ ] **Step 18.5: Commit**

```bash
git add src/collector/curation_handler.py tests/integration/test_curation_handler.py
git commit -m "feat(curation): add tracks list/add/remove routes"
```

---

## Task 19: Integration test — tenancy isolation

**Files:**
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 19.1: Append tenancy tests**

```python
def test_user_b_cannot_see_user_a_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    # User B requests detail
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}",
            path_params={"id": "c1"},
            user_id="user-b",
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404


def test_user_b_cannot_rename_user_a_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "c1"},
            user_id="user-b",
            body={"name": "Hijack"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404


def test_user_b_cannot_delete_user_a_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}",
            path_params={"id": "c1"},
            user_id="user-b",
        ),
        context,
    )
    assert resp["statusCode"] == 404


def test_list_by_style_filters_by_user(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="A", normalized_name="a", now=now,
    )
    fake_repo.create(
        user_id="user-b", style_id="s1", category_id="c2",
        name="B", normalized_name="b", now=now,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            user_id="user-a",
        ),
        context,
    )
    _, body = _read(resp)
    assert body["total"] == 1
    assert body["items"][0]["id"] == "c1"
```

- [ ] **Step 19.2: Run**

Run: `pytest tests/integration/test_curation_handler.py -v -k tenan or user_b or list_by_style_filters`
Expected: 4 tenancy tests PASS (handler already enforces this — no implementation change needed).

- [ ] **Step 19.3: Commit**

```bash
git add tests/integration/test_curation_handler.py
git commit -m "test(curation): add tenancy isolation integration tests"
```

---

## Task 20: Integration test — name conflict, recreate-after-soft-delete, cross-style namesakes

**Files:**
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 20.1: Append tests**

```python
def test_recreate_after_soft_delete(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    # soft-delete
    fake_repo.soft_delete(user_id="u1", category_id="c1", now=now)
    # recreate same name -> should succeed
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "Tech"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["track_count"] == 0
    assert body["id"] != "c1"


def test_cross_style_namesakes_coexist(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    r1 = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "Deep"},
        ),
        context,
    )
    r2 = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s2"},
            body={"name": "Deep"},
        ),
        context,
    )
    assert r1["statusCode"] == 201
    assert r2["statusCode"] == 201
```

- [ ] **Step 20.2: Run**

Run: `pytest tests/integration/test_curation_handler.py -v -k "recreate or cross_style_namesakes"`
Expected: 2 tests PASS.

- [ ] **Step 20.3: Commit**

```bash
git add tests/integration/test_curation_handler.py
git commit -m "test(curation): add recreate-after-soft-delete and cross-style tests"
```

---

## Task 21: Integration test — spec-D contract smoke (`add_tracks_bulk` with transaction_id)

This test validates the cross-spec contract: spec-D will call `add_tracks_bulk` from inside its own transaction, passing `transaction_id`. Even with a placeholder block id (and no FK in spec-C), the row must round-trip.

**Files:**
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 21.1: Append test**

```python
def test_spec_d_contract_add_tracks_bulk_round_trip(fake_repo, context):
    """spec-D will reuse add_tracks_bulk inside its triage finalize TX."""
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {
        "id": "t1", "title": "X", "normalized_title": "x",
    }
    inserted = fake_repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", "block-d-1")],
        now=now,
        transaction_id="tx-from-spec-d",
    )
    assert inserted == 1
    # source_triage_block_id round-trips
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
        ),
        context,
    )
    _, body = _read(resp)
    assert body["items"][0]["source_triage_block_id"] == "block-d-1"
```

- [ ] **Step 21.2: Run**

Run: `pytest tests/integration/test_curation_handler.py -v -k spec_d_contract`
Expected: 1 test PASS.

- [ ] **Step 21.3: Commit**

```bash
git add tests/integration/test_curation_handler.py
git commit -m "test(curation): add spec-D add_tracks_bulk contract smoke"
```

---

## Task 22: Integration test — pagination, search, count rollup

**Files:**
- Modify: `tests/integration/test_curation_handler.py`

- [ ] **Step 22.1: Append tests**

```python
def test_tracks_pagination_limits(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    for i in range(120):
        tid = f"t{i:03}"
        fake_repo.track_meta[tid] = {
            "id": tid, "title": f"S{i}", "normalized_title": f"s{i}",
        }
        fake_repo.add_track(
            user_id="u1", category_id="c1", track_id=tid,
            source_triage_block_id=None, now=now,
        )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"limit": "50", "offset": "100"},
        ),
        context,
    )
    _, body = _read(resp)
    assert body["total"] == 120
    assert len(body["items"]) == 20  # 120 - 100


def test_tracks_search(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    for tid, title in [("t1", "Acid Rain"), ("t2", "Deep Ocean"), ("t3", "Acid Wave")]:
        fake_repo.track_meta[tid] = {
            "id": tid, "title": title,
            "normalized_title": title.lower(),
        }
        fake_repo.add_track(
            user_id="u1", category_id="c1", track_id=tid,
            source_triage_block_id=None, now=now,
        )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"search": "acid"},
        ),
        context,
    )
    _, body = _read(resp)
    assert body["total"] == 2


def test_track_count_rollup_on_list_and_detail(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    for tid in ["t1", "t2", "t3"]:
        fake_repo.track_meta[tid] = {"id": tid}
        fake_repo.add_track(
            user_id="u1", category_id="c1", track_id=tid,
            source_triage_block_id=None, now=now,
        )

    detail = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    _, body = _read(detail)
    assert body["track_count"] == 3

    listing = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
        ),
        context,
    )
    _, body = _read(listing)
    assert body["items"][0]["track_count"] == 3

    # Remove one -> count decrements
    lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}/tracks/{track_id}",
            path_params={"id": "c1", "track_id": "t1"},
        ),
        context,
    )
    detail2 = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    _, body = _read(detail2)
    assert body["track_count"] == 2
```

- [ ] **Step 22.2: Run**

Run: `pytest tests/integration/test_curation_handler.py -v -k "pagination or search or count_rollup"`
Expected: 3 tests PASS.

- [ ] **Step 22.3: Run the full curation suite as a final guardrail**

Run: `pytest tests/unit/test_curation_schemas.py tests/unit/test_categories_service.py tests/unit/test_categories_repository.py tests/unit/test_migration_14_sql.py tests/integration/test_curation_handler.py -v`
Expected: all green (≈70 tests).

- [ ] **Step 22.4: Run the entire test suite to verify no regressions in unrelated specs**

Run: `pytest -q`
Expected: full repo suite green.

- [ ] **Step 22.5: Commit**

```bash
git add tests/integration/test_curation_handler.py
git commit -m "test(curation): add pagination, search, and count rollup tests"
```

---

## Task 23: Terraform — Lambda function for curation_handler

**Files:**
- Create: `infra/curation_lambda.tf`
- Modify (only if needed): `infra/main.tf` to reference the new file (Terraform auto-includes `*.tf` in the directory; usually no change required).

- [ ] **Step 23.1: Read existing Lambda definitions for the auth handler to match patterns**

Read: `infra/auth_lambda.tf` (or whatever file holds `aws_lambda_function.auth`). Note the role / log group naming, env vars, runtime, handler entry, source_zip path, and `depends_on` chain.

Run: `ls infra/*.tf` and `grep -l "aws_lambda_function" infra/*.tf` to locate.

- [ ] **Step 23.2: Write the curation Lambda Terraform**

```hcl
# infra/curation_lambda.tf

resource "aws_iam_role" "curation_lambda" {
  name = "${var.project}-${var.environment}-curation-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "curation_lambda_basic" {
  role       = aws_iam_role.curation_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "curation_lambda_data_api" {
  name = "${var.project}-${var.environment}-curation-data-api"
  role = aws_iam_role.curation_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction",
          "rds-data:BatchExecuteStatement"
        ]
        Resource = aws_rds_cluster.aurora.arn
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = data.aws_secretsmanager_secret.aurora_master.arn
      },
    ]
  })
}

resource "aws_lambda_function" "curation" {
  function_name    = "${var.project}-${var.environment}-curation"
  role             = aws_iam_role.curation_lambda.arn
  runtime          = "python3.12"
  handler          = "collector.curation_handler.lambda_handler"
  filename         = "${path.module}/../dist/collector.zip"
  source_code_hash = filebase64sha256("${path.module}/../dist/collector.zip")
  timeout          = 30
  memory_size      = 512

  environment {
    variables = {
      AURORA_CLUSTER_ARN = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN  = data.aws_secretsmanager_secret.aurora_master.arn
      AURORA_DATABASE    = var.aurora_database_name
      LOG_LEVEL          = "INFO"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.curation_lambda_basic,
    aws_iam_role_policy.curation_lambda_data_api,
  ]
}

resource "aws_lambda_permission" "curation_invoke" {
  statement_id  = "AllowAPIGatewayInvokeCuration"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.curation.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
```

NOTE: replace resource references (`aws_rds_cluster.aurora`, `data.aws_secretsmanager_secret.aurora_master`, `aws_apigatewayv2_api.main`, `var.aurora_database_name`, `var.project`, `var.environment`) with whatever names the existing infra uses. Look them up via:

```
grep -n "aws_rds_cluster\." infra/*.tf | head
grep -n "data.aws_secretsmanager_secret" infra/*.tf | head
grep -n "aws_apigatewayv2_api" infra/*.tf | head
grep -n "aurora_database_name\|var.project\|var.environment" infra/*.tf | head
```

- [ ] **Step 23.3: Run terraform validate**

Run:
```bash
cd infra && terraform init -upgrade && terraform validate
```
Expected: Success! The configuration is valid.

If `terraform validate` complains about a missing reference, fix the reference name to match the actual resource in this repo.

- [ ] **Step 23.4: Commit**

```bash
git add infra/curation_lambda.tf
git commit -m "feat(curation): add curation Lambda function in terraform"
```

---

## Task 24: Terraform — API Gateway integration + 9 routes

**Files:**
- Create: `infra/curation_routes.tf`

- [ ] **Step 24.1: Write the routes file**

```hcl
# infra/curation_routes.tf

resource "aws_apigatewayv2_integration" "curation" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.curation.invoke_arn
  payload_format_version = "2.0"
}

locals {
  curation_routes = [
    "POST /styles/{style_id}/categories",
    "GET /styles/{style_id}/categories",
    "GET /categories",
    "GET /categories/{id}",
    "PATCH /categories/{id}",
    "DELETE /categories/{id}",
    "PUT /styles/{style_id}/categories/order",
    "GET /categories/{id}/tracks",
    "POST /categories/{id}/tracks",
    "DELETE /categories/{id}/tracks/{track_id}",
  ]
}

resource "aws_apigatewayv2_route" "curation" {
  for_each  = toset(local.curation_routes)
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.curation.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

NOTE: confirm the authorizer resource name matches the existing one from spec-A. Likely names: `aws_apigatewayv2_authorizer.jwt` or `aws_apigatewayv2_authorizer.lambda_jwt`. Locate via:

```
grep -n "aws_apigatewayv2_authorizer" infra/*.tf | head
```

Also note the route count in `local.curation_routes` is 10, not 9 — the spec lists 9 high-level operations but the table above includes both `GET /categories/{id}/tracks` (list) and `DELETE /categories/{id}/tracks/{track_id}` (remove), totalling 10 distinct route keys. This is correct; the spec collapsed list+remove into separate items implicitly.

- [ ] **Step 24.2: Run terraform validate**

```bash
cd infra && terraform validate
```
Expected: Success.

- [ ] **Step 24.3: Run terraform plan and review**

```bash
cd infra && terraform plan -out=/tmp/curation.tfplan
```
Expected: plan adds the curation Lambda + role + policy + integration + 10 routes + permission. No deletions / replacements of existing resources.

If the plan shows churn on existing resources (auth Lambda, etc.), abort and inspect — likely a resource-name collision. Adjust resource names in the new files until the plan is purely additive.

- [ ] **Step 24.4: Commit**

```bash
git add infra/curation_routes.tf
git commit -m "feat(curation): wire api gateway routes for curation handler"
```

---

## Task 25: Update `docs/data-model.md` with new tables

**Files:**
- Modify: `docs/data-model.md`

- [ ] **Step 25.1: Append the new sections**

Find the next section number (after the last existing one, e.g. §1.13 or wherever auth tables ended) and append:

```markdown
### 1.X categories

User-curation Layer 1 — permanent per-(user, style) track libraries.

| Column          | Type           | Constraints                                                |
|-----------------|----------------|------------------------------------------------------------|
| id              | String(36)     | PK (UUID)                                                  |
| user_id         | String(36)     | NOT NULL, FK -> users.id                                   |
| style_id        | String(36)     | NOT NULL, FK -> clouder_styles.id                          |
| name            | Text           | NOT NULL (display)                                         |
| normalized_name | Text           | NOT NULL (lower + trim + collapsed whitespace)             |
| position        | Integer        | NOT NULL, default=0                                        |
| created_at      | DateTime(tz)   | NOT NULL                                                   |
| updated_at      | DateTime(tz)   | NOT NULL                                                   |
| deleted_at      | DateTime(tz)   | nullable (soft-delete)                                     |

**Indexes:**
- `uq_categories_user_style_normname` UNIQUE (user_id, style_id, normalized_name) WHERE deleted_at IS NULL
- `idx_categories_user_style_position` (user_id, style_id, position) WHERE deleted_at IS NULL
- `idx_categories_user_created` (user_id, created_at DESC) WHERE deleted_at IS NULL

### 1.Y category_tracks

Membership of canonical tracks in user categories.

| Column                  | Type         | Constraints                                                |
|-------------------------|--------------|------------------------------------------------------------|
| category_id             | String(36)   | PK (composite), FK -> categories.id                        |
| track_id                | String(36)   | PK (composite), FK -> clouder_tracks.id                    |
| added_at                | DateTime(tz) | NOT NULL                                                   |
| source_triage_block_id  | String(36)   | nullable; FK added by spec-D (ON DELETE SET NULL)          |

**PK:** (category_id, track_id) — UNIQUE makes add idempotent.

**Indexes:**
- `idx_category_tracks_category_added` (category_id, added_at DESC, track_id)

`source_triage_block_id` is NULL for direct adds and set by spec-D's triage finalize.
```

Replace `1.X` and `1.Y` with the next free numbers.

- [ ] **Step 25.2: Commit**

```bash
git add docs/data-model.md
git commit -m "docs(data-model): document categories and category_tracks tables"
```

---

## Task 26: Final smoke — full suite + plan close-out

- [ ] **Step 26.1: Run the entire suite**

Run: `pytest -q`
Expected: green.

- [ ] **Step 26.2: Run alembic-check locally**

```bash
export PYTHONPATH=src
docker run --rm -d --name pg-spec-c -e POSTGRES_PASSWORD=postgres -p 5433:5432 postgres:16 || true
sleep 3
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/postgres'
alembic upgrade head
docker rm -f pg-spec-c || true
```
Expected: `alembic upgrade head` runs through 14 without error.

(Skip the docker step if you're confident CI will catch it; CI runs `alembic-check` against an ephemeral pg.)

- [ ] **Step 26.3: Confirm git log**

Run: `git log --oneline | head -30`
Expected: tasks 1–25 each produced one commit. No squash, no amend.

- [ ] **Step 26.4: Push the branch**

Run: `git push -u origin worktree-user_flow_spec_c`

- [ ] **Step 26.5: Open a PR**

Use the `gh pr create` flow per repo's CLAUDE.md commit/PR policy. Title:

```
feat(curation): spec-C categories
```

Body should reference the design and plan docs:

```
Implements docs/superpowers/specs/2026-04-26-spec-C-categories-design.md
following docs/superpowers/plans/2026-04-26-spec-C-categories.md.

## Summary
- New `categories` and `category_tracks` tables (alembic 14)
- New `collector/curation/` package + `curation_handler.py` Lambda
- 10 JWT-gated routes (per spec §5)
- Spec-D contract: `add_tracks_bulk(...)` ready

## Test plan
- [x] pytest -q
- [x] alembic-check
- [x] terraform validate + plan (additive only)
```

---

## Self-Review Notes

- **Spec coverage:** Every spec section §3 (D1–D18 decisions) and §5 (routes 5.1–5.10) maps to a task. §4 schema is Task 1. §6 code layout is Tasks 2–18. §7 infrastructure is Tasks 23–24. §8 testing is Tasks 4, 5–12, 13–22. §9.3 spec-D contract is Task 21. §10 acceptance criteria are checked across Tasks 22–26.
- **Type consistency:** `CategoryRow` defined in Task 5 with fields used identically in Tasks 6–18. `TrackInCategoryRow` defined in Task 5, used in Tasks 12 and 18. `add_tracks_bulk` signature `(user_id, category_id, items, now, transaction_id=None)` is consistent across Tasks 10, 11, 17, 21.
- **No placeholders:** Every task has full code or a precise instruction (Tasks 23–24 ask the engineer to grep for actual resource names, but provide the exact pattern).
- **Frequent commits:** Each task ends with one commit. 26 tasks → 26 commits. Conventional Commits format throughout.
