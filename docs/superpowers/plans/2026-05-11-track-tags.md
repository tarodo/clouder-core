# Track Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend support for per-user track tags inside shared style categories — vocabulary CRUD, many-to-many junction, AND/OR filter on the categories list endpoint, cascade cleanup when a track leaves its last active category.

**Architecture:** Two new tables (`user_tags`, `track_tags`). One new repository (`TagsRepository`) sitting next to `CategoriesRepository`. Cleanup is app-level inside the same Data API transaction as the originating category mutation. Tag fan-in is one extra round-trip per page. All routes live in the existing `beatport-prod-curation` Lambda.

**Tech Stack:** Python 3.12, Alembic, SQLAlchemy (autogen only), RDS Data API (`DataAPIClient`), pytest, AWS API Gateway HTTP API.

**Spec:** `docs/superpowers/specs/2026-05-11-track-tags-design.md`.

---

## File Structure

**Create:**
- `alembic/versions/20260511_17_track_tags.py` — schema migration.
- `src/collector/curation/tags_repository.py` — `TagsRepository`, dataclasses, factory.
- `tests/unit/test_tags_repository.py` — repository unit tests.

**Modify:**
- `src/collector/db_models.py` — add `UserTag`, `TrackTag` SQLAlchemy models (autogen only).
- `src/collector/curation/__init__.py` — add `TagNameConflictError`, `TagNotFoundError`, `TrackNotInAnyCategoryError`; re-export `TagsRepository`/dataclasses/factory.
- `src/collector/curation/categories_repository.py` — extend `remove_track`, `soft_delete`, `list_tracks`; extend `TrackInCategoryRow`.
- `src/collector/curation_handler.py` — register new routes (`_ROUTE_TABLE` dict entries) + handler functions + `_tags_factory`.
- `scripts/generate_openapi.py` — append routes to `ROUTES`.
- `tests/unit/test_categories_repository.py` — tests for the extended methods.
- `tests/unit/test_curation_handler.py` — handler-level tests for new routes and filter param.

**Caller audit (verified before plan was written):**
- `categories_service.py` does not call `remove_track`, `soft_delete`, or `list_tracks` — these are only invoked from `curation_handler.py`. Adding the optional `tags_repo` keyword to those repo methods is therefore handler-only.
- `_ROUTE_TABLE` (`curation_handler.py` ~line 833) is `dict["METHOD /path", (handler, factory)]` keyed by `event.requestContext.routeKey`; each handler signature is `(event, repo, user_id, correlation_id)`. Tag routes register a new `_tags_factory`. Existing handlers needing both repos (`_handle_list_tracks`, `_handle_remove_track`, `_handle_soft_delete`) instantiate the second repo inline via `create_default_tags_repository()` — same pattern as `_finalize_triage_block`.

**Out of scope:**
- Frontend.
- `docs/openapi.yaml` regeneration is a one-off command at the very end (Task 8).

---

## Task 0: Add curation exception subclasses

**Files:**
- Modify: `src/collector/curation/__init__.py`

The existing `NameConflictError`, `NotFoundError`, and `BadQueryParamError` carry fixed `error_code`/`http_status`. Reusing them would surface generic codes (`"name_conflict"`, `"bad_query_param"`) instead of the spec-mandated codes (`"tag_name_conflict"`, `"invalid_name"`, etc.), and HTTP 404 instead of 422 for the category-membership rule. We add thin subclasses so the central `_curation_error_response` mapper handles routing/codes automatically — no per-route try/except needed in handlers.

- [ ] **Step 1: Append new classes to `src/collector/curation/__init__.py`**

After the existing `NameConflictError` / `NotFoundError` / `BadQueryParamError` definitions (~line 60–80), add:

```python
class TagNameConflictError(NameConflictError):
    error_code = "tag_name_conflict"


class TagNotFoundError(NotFoundError):
    def __init__(self, message: str = "Tag not found") -> None:
        super().__init__("tag_not_found", message)


class TrackNotInAnyCategoryError(CurationError):
    error_code = "track_not_in_any_category"
    http_status = 422


class InvalidTagNameError(BadQueryParamError):
    error_code = "invalid_name"


class InvalidTagColorError(BadQueryParamError):
    error_code = "invalid_color"


class InvalidTagPayloadError(BadQueryParamError):
    error_code = "invalid_payload"


class InvalidTagIdsError(BadQueryParamError):
    error_code = "invalid_tag_ids"


class TooManyTagsError(BadQueryParamError):
    error_code = "too_many_tags"


class InvalidMatchError(BadQueryParamError):
    error_code = "invalid_match"
```

- [ ] **Step 2: Run unit suite to confirm no regressions**

Run: `pytest tests/unit -q`
Expected: green.

- [ ] **Step 3: Commit**

```bash
git add src/collector/curation/__init__.py
git commit -m "feat(curation): add tag-domain exception subclasses"
```

---

## Task 1: Migration + SQLAlchemy models

**Files:**
- Create: `alembic/versions/20260511_17_track_tags.py`
- Modify: `src/collector/db_models.py`

- [ ] **Step 1: Verify current Alembic head**

Run: `PYTHONPATH=src .venv/bin/alembic heads`
Expected output: `20260509_16 (head)`. Use it as `down_revision`.

- [ ] **Step 2: Create migration file**

Write `alembic/versions/20260511_17_track_tags.py`:

```python
"""user_tags and track_tags

Revision ID: 20260511_17
Revises: 20260509_16
Create Date: 2026-05-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260511_17"
down_revision = "20260509_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_tags_user", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "normalized_name", name="uq_user_tags_user_normalized_name"
        ),
    )
    op.create_index("idx_user_tags_user_id", "user_tags", ["user_id"])

    op.create_table(
        "track_tags",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "track_id", "tag_id"),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["clouder_tracks.id"],
            name="fk_track_tags_track",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["user_tags.id"],
            name="fk_track_tags_tag",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_track_tags_user",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_track_tags_user_tag", "track_tags", ["user_id", "tag_id"]
    )
    op.create_index(
        "idx_track_tags_user_track", "track_tags", ["user_id", "track_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_track_tags_user_track", table_name="track_tags")
    op.drop_index("idx_track_tags_user_tag", table_name="track_tags")
    op.drop_table("track_tags")
    op.drop_index("idx_user_tags_user_id", table_name="user_tags")
    op.drop_table("user_tags")
```

- [ ] **Step 3: Add SQLAlchemy models to `src/collector/db_models.py`**

Append after the existing category models (search for `class Category` to find the right neighbourhood). Add:

```python
class UserTag(Base):
    __tablename__ = "user_tags"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    normalized_name = Column(Text, nullable=False)
    color = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", name="uq_user_tags_user_normalized_name"),
    )


class TrackTag(Base):
    __tablename__ = "track_tags"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    track_id = Column(String(36), ForeignKey("clouder_tracks.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(String(36), ForeignKey("user_tags.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
```

Imports likely already include `Column`, `String`, `Text`, `DateTime`, `ForeignKey`, `UniqueConstraint` — verify and add what's missing.

- [ ] **Step 4: Run migration locally**

```
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: each command exits 0, no errors. The down/up round-trip proves `downgrade()` is correct.

- [ ] **Step 5: Run test suite to confirm nothing regressed**

Run: `pytest -q`
Expected: all green (no new tests yet; this catches db_models import errors).

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/20260511_17_track_tags.py src/collector/db_models.py
# Generate message via caveman-commit, then:
git commit -m "feat(db): add user_tags and track_tags tables"
```

---

## Task 2: TagsRepository vocabulary CRUD

**Files:**
- Create: `src/collector/curation/tags_repository.py`
- Create: `tests/unit/test_tags_repository.py`
- Modify: `src/collector/curation/__init__.py`

- [ ] **Step 1: Write failing tests for dataclasses + constructor**

Create `tests/unit/test_tags_repository.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    TagNameConflictError,
    TagNotFoundError,
    TrackNotInAnyCategoryError,
)
from collector.curation.tags_repository import (
    TagRow,
    TagsRepository,
    TrackTagRow,
)


def _now() -> datetime:
    return datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)


def _make() -> tuple[TagsRepository, MagicMock]:
    data_api = MagicMock()
    return TagsRepository(data_api=data_api), data_api


def test_repository_constructs() -> None:
    repo, _ = _make()
    assert repo is not None


def test_tag_row_dataclass_shape() -> None:
    row = TagRow(
        id="tg1",
        name="Vocal",
        color="#ff8800",
        created_at="2026-05-11T12:00:00Z",
        updated_at="2026-05-11T12:00:00Z",
    )
    assert row.id == "tg1"
    assert row.color == "#ff8800"


def test_track_tag_row_dataclass_shape() -> None:
    row = TrackTagRow(track_id="t1", tag_id="tg1", name="Vocal", color="#ff8800")
    assert row.track_id == "t1"
    assert row.tag_id == "tg1"
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/unit/test_tags_repository.py -q`
Expected: ImportError (`tags_repository` module missing).

- [ ] **Step 3: Create the repository file with dataclasses + stub class**

Create `src/collector/curation/tags_repository.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Literal

from collector.data_api import DataAPIClient
from collector.settings import get_data_api_settings

from . import (
    PaginatedResult,
    TagNameConflictError,
    TagNotFoundError,
    TrackNotInAnyCategoryError,
)


@dataclass(frozen=True)
class TagRow:
    id: str
    name: str
    color: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TrackTagRow:
    track_id: str
    tag_id: str
    name: str
    color: str


class TagsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api


def create_default_tags_repository() -> TagsRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    from collector.data_api import create_default_data_api_client

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return TagsRepository(data_api=data_api)
```

All three exception classes are added by Task 0; if Task 0 was skipped this import will fail — fix by completing Task 0 first.

- [ ] **Step 4: Verify tests now pass**

Run: `pytest tests/unit/test_tags_repository.py -q`
Expected: 3 passed.

- [ ] **Step 5: Write failing test for `create_tag`**

Add to `tests/unit/test_tags_repository.py`:

```python
def test_create_tag_inserts_and_returns_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "tg1",
            "name": "Vocal",
            "color": "#ff8800",
            "created_at": "2026-05-11T12:00:00Z",
            "updated_at": "2026-05-11T12:00:00Z",
        }
    ]

    row = repo.create_tag(
        user_id="u1",
        tag_id="tg1",
        name="Vocal",
        normalized_name="vocal",
        color="#ff8800",
        now=_now(),
    )

    assert isinstance(row, TagRow)
    assert row.id == "tg1"
    call = data_api.execute.call_args
    assert "INSERT INTO user_tags" in call.args[0]
    params = call.args[1]
    assert params["user_id"] == "u1"
    assert params["normalized_name"] == "vocal"
    assert params["color"] == "#ff8800"
```

- [ ] **Step 6: Run, expect failure**

Run: `pytest tests/unit/test_tags_repository.py::test_create_tag_inserts_and_returns_row -q`
Expected: AttributeError or NotImplementedError.

- [ ] **Step 7: Implement `create_tag`**

Add to `TagsRepository`:

```python
def create_tag(
    self,
    *,
    user_id: str,
    tag_id: str,
    name: str,
    normalized_name: str,
    color: str,
    now: datetime,
) -> TagRow:
    try:
        rows = self._data_api.execute(
            """
            INSERT INTO user_tags (
                id, user_id, name, normalized_name, color, created_at, updated_at
            ) VALUES (
                :id, :user_id, :name, :normalized_name, :color, :created_at, :updated_at
            )
            RETURNING id, name, color, created_at, updated_at
            """,
            {
                "id": tag_id,
                "user_id": user_id,
                "name": name,
                "normalized_name": normalized_name,
                "color": color,
                "created_at": now,
                "updated_at": now,
            },
        )
    except Exception as exc:
        if "uq_user_tags_user_normalized_name" in str(exc):
            raise TagNameConflictError(
                "Tag with this name already exists"
            ) from exc
        raise
    r = rows[0]
    return TagRow(
        id=r["id"],
        name=r["name"],
        color=r["color"],
        created_at=str(r["created_at"]),
        updated_at=str(r["updated_at"]),
    )
```

This mirrors the existing string-sniff pattern in `categories_repository.py:127` (`uq_categories_user_style_normname`). `TagNameConflictError` takes a single `message` arg — `error_code = "tag_name_conflict"` is class-level so the central `_curation_error_response` mapper emits the correct envelope.

- [ ] **Step 8: Add tests + impl for `list_tags`, `get_tag`, `rename_tag`, `delete_tag`**

Tests to add — pattern matches `test_categories_repository.py`:

```python
def test_list_tags_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [
            {"id": "tg1", "name": "Vocal", "color": "#ff8800",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
        ],
        [{"total": 1}],
    ]
    page = repo.list_tags(user_id="u1", limit=20, offset=0, search=None)
    assert page.total == 1
    assert page.items[0].id == "tg1"


def test_get_tag_returns_none_when_missing() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    assert repo.get_tag(user_id="u1", tag_id="missing") is None


def test_rename_tag_updates_returned_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {"id": "tg1", "name": "Vocal F", "color": "#ff8800",
         "created_at": "2026-05-11T12:00:00Z",
         "updated_at": "2026-05-11T12:01:00Z"}
    ]
    row = repo.rename_tag(
        user_id="u1", tag_id="tg1", name="Vocal F",
        normalized_name="vocal f", color=None, now=_now(),
    )
    assert row.name == "Vocal F"


def test_rename_tag_raises_when_no_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    with pytest.raises(TagNotFoundError):
        repo.rename_tag(
            user_id="u1", tag_id="missing", name="X",
            normalized_name="x", color=None, now=_now(),
        )


def test_rename_tag_maps_unique_violation() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = Exception("uq_user_tags_user_normalized_name")
    with pytest.raises(TagNameConflictError):
        repo.rename_tag(
            user_id="u1", tag_id="tg1", name="Vocal",
            normalized_name="vocal", color=None, now=_now(),
        )


def test_delete_tag_returns_true_on_delete() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"id": "tg1"}]
    assert repo.delete_tag(user_id="u1", tag_id="tg1") is True
```

Implementations:

```python
def list_tags(
    self,
    *,
    user_id: str,
    limit: int,
    offset: int,
    search: str | None,
) -> PaginatedResult[TagRow]:
    params: dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}
    search_clause = ""
    if search and search.strip():
        search_clause = " AND normalized_name LIKE :search "
        params["search"] = f"{search.strip().lower()}%"
    rows = self._data_api.execute(
        f"""
        SELECT id, name, color, created_at, updated_at
        FROM user_tags
        WHERE user_id = :user_id {search_clause}
        ORDER BY normalized_name ASC
        LIMIT :limit OFFSET :offset
        """,
        params,
    )
    count_params = {"user_id": user_id}
    count_clause = ""
    if "search" in params:
        count_clause = " AND normalized_name LIKE :search "
        count_params["search"] = params["search"]
    total_rows = self._data_api.execute(
        f"SELECT COUNT(*) AS total FROM user_tags WHERE user_id = :user_id {count_clause}",
        count_params,
    )
    total = int(total_rows[0]["total"]) if total_rows else 0
    items = [
        TagRow(
            id=r["id"], name=r["name"], color=r["color"],
            created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
        )
        for r in rows
    ]
    return PaginatedResult(items=items, total=total, limit=limit, offset=offset)


def get_tag(self, *, user_id: str, tag_id: str) -> TagRow | None:
    rows = self._data_api.execute(
        """
        SELECT id, name, color, created_at, updated_at
        FROM user_tags
        WHERE user_id = :user_id AND id = :tag_id
        """,
        {"user_id": user_id, "tag_id": tag_id},
    )
    if not rows:
        return None
    r = rows[0]
    return TagRow(
        id=r["id"], name=r["name"], color=r["color"],
        created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def rename_tag(
    self,
    *,
    user_id: str,
    tag_id: str,
    name: str | None,
    normalized_name: str | None,
    color: str | None,
    now: datetime,
) -> TagRow:
    sets: list[str] = ["updated_at = :updated_at"]
    params: dict[str, Any] = {
        "user_id": user_id, "tag_id": tag_id, "updated_at": now,
    }
    if name is not None:
        sets.append("name = :name")
        params["name"] = name
        sets.append("normalized_name = :normalized_name")
        params["normalized_name"] = normalized_name
    if color is not None:
        sets.append("color = :color")
        params["color"] = color
    try:
        rows = self._data_api.execute(
            f"""
            UPDATE user_tags SET {", ".join(sets)}
            WHERE user_id = :user_id AND id = :tag_id
            RETURNING id, name, color, created_at, updated_at
            """,
            params,
        )
    except Exception as exc:
        if "uq_user_tags_user_normalized_name" in str(exc):
            raise TagNameConflictError(
                "Tag with this name already exists"
            ) from exc
        raise
    if not rows:
        raise TagNotFoundError()
    r = rows[0]
    return TagRow(
        id=r["id"], name=r["name"], color=r["color"],
        created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def delete_tag(self, *, user_id: str, tag_id: str) -> bool:
    rows = self._data_api.execute(
        """
        DELETE FROM user_tags
        WHERE user_id = :user_id AND id = :tag_id
        RETURNING id
        """,
        {"user_id": user_id, "tag_id": tag_id},
    )
    return bool(rows)
```

- [ ] **Step 9: Run tests, expect all pass**

Run: `pytest tests/unit/test_tags_repository.py -q`
Expected: ~9 passed.

- [ ] **Step 10: Re-export from package**

Edit `src/collector/curation/__init__.py` to include `TagsRepository`, `TagRow`, `TrackTagRow`, `create_default_tags_repository` (mirror how `CategoriesRepository` is exposed).

- [ ] **Step 11: Run full unit suite**

Run: `pytest tests/unit -q`
Expected: all green.

- [ ] **Step 12: Commit**

```bash
git add src/collector/curation/tags_repository.py src/collector/curation/__init__.py tests/unit/test_tags_repository.py
git commit -m "feat(curation): add TagsRepository vocabulary CRUD"
```

---

## Task 3: TagsRepository track-tag ops + cleanup helper

**Files:**
- Modify: `src/collector/curation/tags_repository.py`
- Modify: `tests/unit/test_tags_repository.py`

- [ ] **Step 1: Write failing test for `set_track_tags` happy path**

Add to test file:

```python
def test_set_track_tags_replaces_set() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    # 1: category membership probe -> 1 row.
    # 2: tag ownership probe -> 2 rows.
    # 3: DELETE existing.
    # 4: INSERT new.
    # 5: SELECT joined for return.
    data_api.execute.side_effect = [
        [{"x": 1}],
        [{"id": "tg1"}, {"id": "tg2"}],
        [],
        [],
        [
            {"id": "tg1", "name": "Vocal", "color": "#f00",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
            {"id": "tg2", "name": "Dark", "color": "#000",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
        ],
    ]
    result = repo.set_track_tags(
        user_id="u1", track_id="t1", tag_ids=["tg1", "tg2"], now=_now(),
    )
    assert [r.id for r in result] == ["tg1", "tg2"]


def test_set_track_tags_empty_clears() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"x": 1}],   # category probe
        [],           # DELETE existing (no INSERT, no SELECT-after needed)
        [],           # SELECT joined returns empty
    ]
    result = repo.set_track_tags(user_id="u1", track_id="t1", tag_ids=[], now=_now())
    assert result == []


def test_set_track_tags_raises_when_track_not_in_category() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [],  # category probe returns no rows
    ]
    with pytest.raises(TrackNotInAnyCategoryError):
        repo.set_track_tags(user_id="u1", track_id="t1", tag_ids=["tg1"], now=_now())


def test_set_track_tags_raises_when_foreign_tag() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"x": 1}],         # category probe ok
        [{"id": "tg1"}],    # only one of two requested tag_ids is owned
    ]
    with pytest.raises(TagNotFoundError):
        repo.set_track_tags(
            user_id="u1", track_id="t1", tag_ids=["tg1", "tg2"], now=_now(),
        )
```

`TrackNotInAnyCategoryError` is a `CurationError` with `http_status = 422`; `TagNotFoundError` is a `NotFoundError` subclass — both already added in Task 0. The central `_curation_error_response` mapper will translate them to the correct HTTP envelopes without per-route try/except.

- [ ] **Step 2: Run, expect failures**

Run: `pytest tests/unit/test_tags_repository.py -q`
Expected: 4 failures.

- [ ] **Step 3: Implement `set_track_tags` + private helper**

Add to `TagsRepository`:

```python
def _assert_track_in_any_active_category(
    self, *, user_id: str, track_id: str, transaction_id: str | None
) -> None:
    rows = self._data_api.execute(
        """
        SELECT 1
        FROM category_tracks ct
        JOIN categories c ON c.id = ct.category_id
        WHERE c.user_id = :user_id
          AND ct.track_id = :track_id
          AND c.deleted_at IS NULL
        LIMIT 1
        """,
        {"user_id": user_id, "track_id": track_id},
        transaction_id=transaction_id,
    )
    if not rows:
        raise TrackNotInAnyCategoryError(
            "Track is not in any of the user's categories",
        )


def set_track_tags(
    self,
    *,
    user_id: str,
    track_id: str,
    tag_ids: list[str],
    now: datetime,
    transaction_id: str | None = None,
) -> list[TagRow]:
    # de-dup while preserving caller order
    ordered: list[str] = []
    seen: set[str] = set()
    for t in tag_ids:
        if t not in seen:
            ordered.append(t)
            seen.add(t)

    def _do(tx_id: str) -> list[TagRow]:
        self._assert_track_in_any_active_category(
            user_id=user_id, track_id=track_id, transaction_id=tx_id,
        )
        if ordered:
            placeholders = ", ".join(f":tg{i}" for i in range(len(ordered)))
            params = {f"tg{i}": tid for i, tid in enumerate(ordered)}
            params["user_id"] = user_id
            found = self._data_api.execute(
                f"SELECT id FROM user_tags WHERE user_id = :user_id AND id IN ({placeholders})",
                params,
                transaction_id=tx_id,
            )
            found_ids = {r["id"] for r in found}
            missing = [t for t in ordered if t not in found_ids]
            if missing:
                raise TagNotFoundError(f"Unknown tag id: {missing[0]}")

        self._data_api.execute(
            "DELETE FROM track_tags WHERE user_id = :user_id AND track_id = :track_id",
            {"user_id": user_id, "track_id": track_id},
            transaction_id=tx_id,
        )
        if ordered:
            value_clauses: list[str] = []
            params = {
                "user_id": user_id,
                "track_id": track_id,
                "created_at": now,
            }
            for i, tid in enumerate(ordered):
                value_clauses.append(
                    f"(:user_id, :track_id, :tg{i}, :created_at)"
                )
                params[f"tg{i}"] = tid
            self._data_api.execute(
                f"""
                INSERT INTO track_tags (user_id, track_id, tag_id, created_at)
                VALUES {", ".join(value_clauses)}
                """,
                params,
                transaction_id=tx_id,
            )

        rows = self._data_api.execute(
            """
            SELECT ut.id, ut.name, ut.color, ut.created_at, ut.updated_at
            FROM track_tags tt
            JOIN user_tags ut ON ut.id = tt.tag_id
            WHERE tt.user_id = :user_id AND tt.track_id = :track_id
            ORDER BY ut.normalized_name ASC
            """,
            {"user_id": user_id, "track_id": track_id},
            transaction_id=tx_id,
        )
        return [
            TagRow(
                id=r["id"], name=r["name"], color=r["color"],
                created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    if transaction_id is not None:
        return _do(transaction_id)
    with self._data_api.transaction() as tx_id:
        return _do(tx_id)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/unit/test_tags_repository.py -q`
Expected: previous + 4 new = pass.

- [ ] **Step 5: Add `add_track_tag`, `remove_track_tag`, `list_tags_for_tracks`, `cleanup_orphaned_track_tags`**

Tests:

```python
def test_add_track_tag_idempotent() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"x": 1}],          # category probe
        [{"id": "tg1"}],     # tag ownership probe
        [],                  # INSERT ON CONFLICT DO NOTHING
        [                    # SELECT after
            {"id": "tg1", "name": "Vocal", "color": "#f00",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
        ],
    ]
    out = repo.add_track_tag(user_id="u1", track_id="t1", tag_id="tg1", now=_now())
    assert [r.id for r in out] == ["tg1"]


def test_add_track_tag_raises_when_track_not_in_category() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [[]]  # category probe empty
    with pytest.raises(TrackNotInAnyCategoryError):
        repo.add_track_tag(user_id="u1", track_id="t1", tag_id="tg1", now=_now())


def test_add_track_tag_raises_when_foreign_tag() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"x": 1}],   # category probe ok
        [],           # tag ownership probe — empty (not owned)
    ]
    with pytest.raises(TagNotFoundError):
        repo.add_track_tag(user_id="u1", track_id="t1", tag_id="tg1", now=_now())


def test_remove_track_tag_returns_true_on_delete() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"tag_id": "tg1"}]
    assert repo.remove_track_tag(user_id="u1", track_id="t1", tag_id="tg1") is True


def test_list_tags_for_tracks_groups_by_track() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {"track_id": "t1", "id": "tg1", "name": "Vocal", "color": "#f00"},
        {"track_id": "t1", "id": "tg2", "name": "Dark",  "color": "#000"},
        {"track_id": "t2", "id": "tg1", "name": "Vocal", "color": "#f00"},
    ]
    grouped = repo.list_tags_for_tracks(user_id="u1", track_ids=["t1", "t2"])
    assert [r.tag_id for r in grouped["t1"]] == ["tg1", "tg2"]
    assert [r.tag_id for r in grouped["t2"]] == ["tg1"]


def test_list_tags_for_tracks_empty_input_short_circuits() -> None:
    repo, data_api = _make()
    grouped = repo.list_tags_for_tracks(user_id="u1", track_ids=[])
    assert grouped == {}
    data_api.execute.assert_not_called()


def test_cleanup_orphaned_track_tags_deletes_when_no_categories() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"track_id": "t1"}, {"track_id": "t1"}]
    n = repo.cleanup_orphaned_track_tags(
        user_id="u1", track_ids=["t1"], transaction_id="tx-1",
    )
    assert n == 2
    sql = data_api.execute.call_args.args[0]
    assert "NOT EXISTS" in sql


def test_cleanup_orphaned_track_tags_empty_short_circuits() -> None:
    repo, data_api = _make()
    n = repo.cleanup_orphaned_track_tags(
        user_id="u1", track_ids=[], transaction_id="tx-1",
    )
    assert n == 0
    data_api.execute.assert_not_called()
```

Implementations:

```python
def add_track_tag(
    self,
    *,
    user_id: str,
    track_id: str,
    tag_id: str,
    now: datetime,
    transaction_id: str | None = None,
) -> list[TagRow]:
    def _do(tx_id: str) -> list[TagRow]:
        self._assert_track_in_any_active_category(
            user_id=user_id, track_id=track_id, transaction_id=tx_id,
        )
        owned = self._data_api.execute(
            "SELECT id FROM user_tags WHERE user_id = :user_id AND id = :tag_id",
            {"user_id": user_id, "tag_id": tag_id},
            transaction_id=tx_id,
        )
        if not owned:
            raise TagNotFoundError()
        self._data_api.execute(
            """
            INSERT INTO track_tags (user_id, track_id, tag_id, created_at)
            VALUES (:user_id, :track_id, :tag_id, :created_at)
            ON CONFLICT (user_id, track_id, tag_id) DO NOTHING
            """,
            {"user_id": user_id, "track_id": track_id,
             "tag_id": tag_id, "created_at": now},
            transaction_id=tx_id,
        )
        rows = self._data_api.execute(
            """
            SELECT ut.id, ut.name, ut.color, ut.created_at, ut.updated_at
            FROM track_tags tt
            JOIN user_tags ut ON ut.id = tt.tag_id
            WHERE tt.user_id = :user_id AND tt.track_id = :track_id
            ORDER BY ut.normalized_name ASC
            """,
            {"user_id": user_id, "track_id": track_id},
            transaction_id=tx_id,
        )
        return [
            TagRow(
                id=r["id"], name=r["name"], color=r["color"],
                created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    if transaction_id is not None:
        return _do(transaction_id)
    with self._data_api.transaction() as tx_id:
        return _do(tx_id)


def remove_track_tag(
    self, *, user_id: str, track_id: str, tag_id: str
) -> bool:
    rows = self._data_api.execute(
        """
        DELETE FROM track_tags
        WHERE user_id = :user_id AND track_id = :track_id AND tag_id = :tag_id
        RETURNING tag_id
        """,
        {"user_id": user_id, "track_id": track_id, "tag_id": tag_id},
    )
    return bool(rows)


def list_tags_for_tracks(
    self, *, user_id: str, track_ids: list[str]
) -> dict[str, list[TrackTagRow]]:
    if not track_ids:
        return {}
    placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
    params: dict[str, Any] = {f"t{i}": tid for i, tid in enumerate(track_ids)}
    params["user_id"] = user_id
    rows = self._data_api.execute(
        f"""
        SELECT tt.track_id, ut.id, ut.name, ut.color
        FROM track_tags tt
        JOIN user_tags ut ON ut.id = tt.tag_id
        WHERE tt.user_id = :user_id AND tt.track_id IN ({placeholders})
        ORDER BY tt.track_id, ut.normalized_name ASC
        """,
        params,
    )
    grouped: dict[str, list[TrackTagRow]] = {}
    for r in rows:
        grouped.setdefault(r["track_id"], []).append(
            TrackTagRow(
                track_id=r["track_id"],
                tag_id=r["id"],
                name=r["name"],
                color=r["color"],
            )
        )
    return grouped


def cleanup_orphaned_track_tags(
    self,
    *,
    user_id: str,
    track_ids: list[str],
    transaction_id: str,
) -> int:
    if not track_ids:
        return 0
    placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
    params: dict[str, Any] = {f"t{i}": tid for i, tid in enumerate(track_ids)}
    params["user_id"] = user_id
    rows = self._data_api.execute(
        f"""
        DELETE FROM track_tags
        WHERE user_id = :user_id
          AND track_id IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1 FROM category_tracks ct
              JOIN categories c ON c.id = ct.category_id
              WHERE ct.track_id = track_tags.track_id
                AND c.user_id = :user_id
                AND c.deleted_at IS NULL
          )
        RETURNING track_id
        """,
        params,
        transaction_id=transaction_id,
    )
    return len(rows)
```

- [ ] **Step 6: Run all tests for the module**

Run: `pytest tests/unit/test_tags_repository.py -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/collector/curation/tags_repository.py tests/unit/test_tags_repository.py
git commit -m "feat(curation): add track-tag ops and orphan cleanup to TagsRepository"
```

---

## Task 4: Hook cleanup into CategoriesRepository

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

The existing `remove_track` and `soft_delete` are not wrapped in a transaction. We add the transaction and an optional `tags_repo` parameter; if the caller passes one, we call `cleanup_orphaned_track_tags` inside the same `tx_id`.

- [ ] **Step 1: Write failing test for `remove_track` cleanup call**

Add to `tests/unit/test_categories_repository.py`:

```python
from collector.curation.tags_repository import TagsRepository


def _fake_tags_repo() -> MagicMock:
    m = MagicMock(spec=TagsRepository)
    m.cleanup_orphaned_track_tags.return_value = 0
    return m


def test_remove_track_calls_tags_cleanup() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"id": "c1"}],          # category exists
        [{"track_id": "t1"}],    # DELETE returning
    ]
    tags_repo = _fake_tags_repo()

    ok = repo.remove_track(
        user_id="u1", category_id="c1", track_id="t1", tags_repo=tags_repo,
    )
    assert ok is True
    tags_repo.cleanup_orphaned_track_tags.assert_called_once_with(
        user_id="u1", track_ids=["t1"], transaction_id="tx-1",
    )


def test_remove_track_skips_cleanup_when_nothing_deleted() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [],  # nothing deleted
    ]
    tags_repo = _fake_tags_repo()
    ok = repo.remove_track(
        user_id="u1", category_id="c1", track_id="t1", tags_repo=tags_repo,
    )
    assert ok is False
    tags_repo.cleanup_orphaned_track_tags.assert_not_called()
```

- [ ] **Step 2: Update `remove_track` signature + body**

Modify `src/collector/curation/categories_repository.py:591-615`:

```python
def remove_track(
    self,
    *,
    user_id: str,
    category_id: str,
    track_id: str,
    tags_repo: "TagsRepository | None" = None,
) -> bool:
    with self._data_api.transaction() as tx_id:
        cat_rows = self._data_api.execute(
            """
            SELECT id FROM categories
            WHERE id = :category_id
              AND user_id = :user_id
              AND deleted_at IS NULL
            """,
            {"category_id": category_id, "user_id": user_id},
            transaction_id=tx_id,
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
            transaction_id=tx_id,
        )
        deleted = bool(rows)
        if deleted and tags_repo is not None:
            tags_repo.cleanup_orphaned_track_tags(
                user_id=user_id, track_ids=[track_id], transaction_id=tx_id,
            )
        return deleted
```

Add forward import at the top of the file:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .tags_repository import TagsRepository
```

- [ ] **Step 3: Verify existing `remove_track` tests still pass (no tags_repo passed)**

Run: `pytest tests/unit/test_categories_repository.py -q`
Expected: all green. Existing tests pass `tags_repo=None` by omission.

- [ ] **Step 4: Write failing test for `soft_delete` cleanup**

Add:

```python
def test_soft_delete_cleans_orphaned_tags_for_member_tracks() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"track_id": "t1"}, {"track_id": "t2"}],   # SELECT member tracks
        [{"id": "c1"}],                              # UPDATE deleted_at returning
    ]
    tags_repo = _fake_tags_repo()
    ok = repo.soft_delete(
        user_id="u1", category_id="c1", now=_now(),
        triage_repository=MagicMock(),  # existing arg
        tags_repo=tags_repo,
    )
    assert ok is True
    tags_repo.cleanup_orphaned_track_tags.assert_called_once_with(
        user_id="u1", track_ids=["t1", "t2"], transaction_id="tx-1",
    )
```

If the existing `soft_delete` signature differs (different keyword for triage), check `src/collector/curation/categories_repository.py:337` and update the test accordingly. The new param `tags_repo` is keyword-only.

- [ ] **Step 5: Update `soft_delete` to include cleanup**

Modify the method:

1. Before the existing UPDATE statement, SELECT the member `track_id` set:
   ```sql
   SELECT track_id FROM category_tracks WHERE category_id = :category_id
   ```
2. Run the existing UPDATE / triage side effects unchanged.
3. After the UPDATE, if `tags_repo is not None` and the SELECT returned rows, call `tags_repo.cleanup_orphaned_track_tags(user_id=..., track_ids=[...], transaction_id=tx_id)`.

Add `tags_repo: "TagsRepository | None" = None` to the signature.

- [ ] **Step 6: Run all categories tests**

Run: `pytest tests/unit/test_categories_repository.py -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/collector/curation/categories_repository.py tests/unit/test_categories_repository.py
git commit -m "feat(curation): wire track-tag cleanup into category mutations"
```

---

## Task 5: Extend `list_tracks` with tag filter + tag fan-in

**Files:**
- Modify: `src/collector/curation/categories_repository.py`
- Modify: `tests/unit/test_categories_repository.py`

- [ ] **Step 1: Extend `TrackInCategoryRow` to carry tags**

Modify the dataclass at `categories_repository.py:42-46`:

```python
from typing import Tuple
# Use tuple for frozen-dataclass immutability; convert to list at handler boundary if needed.

@dataclass(frozen=True)
class TrackInCategoryRow:
    track: Mapping[str, Any]
    added_at: str
    source_triage_block_id: str | None
    tags: Tuple["TrackTagRow", ...] = ()
```

Import:
```python
from .tags_repository import TrackTagRow
```

- [ ] **Step 2: Write failing test for tag filter (AND)**

Add:

```python
def test_list_tracks_filters_with_match_all() -> None:
    repo, data_api = _make()
    # category existence, main page query, total count, tags fan-in
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [
            {
                "id": "t1", "title": "X", "mix_name": None,
                "isrc": None, "bpm": None, "length_ms": None,
                "publish_date": None, "spotify_id": None,
                "release_type": None, "is_ai_suspected": None,
                "spotify_release_date": None,
                "artists_json": "[]",
                "label_id": None, "label_name": None,
                "added_at": "2026-05-11T12:00:00Z",
                "source_triage_block_id": None,
            }
        ],
        [{"total": 1}],
        [   # fan-in
            {"track_id": "t1", "id": "tg1", "name": "Vocal", "color": "#f00"},
        ],
    ]
    tags_repo = _fake_tags_repo()
    tags_repo.list_tags_for_tracks.return_value = {
        "t1": [TrackTagRow(track_id="t1", tag_id="tg1", name="Vocal", color="#f00")]
    }
    page = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=20, offset=0, search=None,
        tag_ids=["tg1", "tg2"], tag_match="all",
        tags_repo=tags_repo,
    )
    assert page.total == 1
    assert page.items[0].tags[0].tag_id == "tg1"
    main_sql = data_api.execute.call_args_list[1].args[0]
    assert "GROUP BY track_id" in main_sql
    assert "COUNT(DISTINCT tag_id)" in main_sql


def test_list_tracks_filters_with_match_any() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [],
        [{"total": 0}],
    ]
    tags_repo = _fake_tags_repo()
    tags_repo.list_tags_for_tracks.return_value = {}
    page = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=20, offset=0, search=None,
        tag_ids=["tg1"], tag_match="any",
        tags_repo=tags_repo,
    )
    assert page.total == 0
    main_sql = data_api.execute.call_args_list[1].args[0]
    assert "COUNT(DISTINCT" not in main_sql


def test_list_tracks_no_tag_filter_still_populates_tags() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [
            {
                "id": "t1", "title": "X", "mix_name": None,
                "isrc": None, "bpm": None, "length_ms": None,
                "publish_date": None, "spotify_id": None,
                "release_type": None, "is_ai_suspected": None,
                "spotify_release_date": None,
                "artists_json": "[]",
                "label_id": None, "label_name": None,
                "added_at": "2026-05-11T12:00:00Z",
                "source_triage_block_id": None,
            }
        ],
        [{"total": 1}],
    ]
    tags_repo = _fake_tags_repo()
    tags_repo.list_tags_for_tracks.return_value = {
        "t1": [TrackTagRow(track_id="t1", tag_id="tg1", name="Vocal", color="#f00")]
    }
    page = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=20, offset=0, search=None,
        tags_repo=tags_repo,
    )
    assert page.items[0].tags[0].name == "Vocal"
    tags_repo.list_tags_for_tracks.assert_called_once_with(
        user_id="u1", track_ids=["t1"],
    )
```

- [ ] **Step 3: Extend `list_tracks` signature + body**

Modify `categories_repository.py:617-730`:

1. Add kwargs: `tag_ids: list[str] | None = None`, `tag_match: Literal["all", "any"] = "all"`, `tags_repo: "TagsRepository | None" = None`.
2. If `tag_ids`:
   - Build placeholders `:tag0, :tag1, ...`; add into both main SQL and count SQL.
   - Inject before the existing `{search_clause}`:
     ```sql
     AND ct.track_id IN (
         SELECT track_id FROM track_tags
         WHERE user_id = :user_id AND tag_id IN (...)
         {group_clause}
     )
     ```
     where `group_clause = "GROUP BY track_id HAVING COUNT(DISTINCT tag_id) = :tag_count"` when `tag_match=="all"`, else empty.
   - Add `user_id` and `tag_count` to params.
3. After building the page, if `tags_repo is not None and items`:
   ```python
   grouped = tags_repo.list_tags_for_tracks(
       user_id=user_id,
       track_ids=[r.track["id"] for r in items],
   )
   items = [
       TrackInCategoryRow(
           track=row.track,
           added_at=row.added_at,
           source_triage_block_id=row.source_triage_block_id,
           tags=tuple(grouped.get(row.track["id"], [])),
       )
       for row in items
   ]
   ```

- [ ] **Step 4: Extend `_track_in_category_response` serializer**

Modify `src/collector/curation_handler.py:396`:

```python
def _track_in_category_response(item) -> dict[str, Any]:
    track = dict(item.track)
    track["added_at"] = item.added_at
    track["source_triage_block_id"] = item.source_triage_block_id
    track["tags"] = [
        {"id": t.tag_id, "name": t.name, "color": t.color}
        for t in getattr(item, "tags", ())
    ]
    return track
```

`getattr(..., "tags", ())` keeps the serializer safe for any test fixture that constructs `TrackInCategoryRow` without the new field — the dataclass default is `()` so this should never fire in production.

Add a small unit test in `tests/unit/test_curation_handler.py` confirming `tags` is always present (empty list when row has no tags, populated when it does).

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_categories_repository.py tests/unit/test_curation_handler.py -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation/categories_repository.py src/collector/curation_handler.py tests/unit/test_categories_repository.py tests/unit/test_curation_handler.py
git commit -m "feat(curation): filter category tracks by tags and fan-in tag list"
```

---

## Task 6: Handler routes for tag vocabulary

**Files:**
- Modify: `src/collector/curation_handler.py`
- Modify: `tests/unit/test_curation_handler.py`

> **Dispatcher contract.** `_ROUTE_TABLE` (`curation_handler.py` ~line 833) is `dict["METHOD /path", (handler, factory)]` keyed by `event.requestContext.routeKey`. Each handler signature is `(event, repo, user_id, correlation_id)` — a single repository per route, produced by the matching factory. We do **not** widen this signature. Tag routes register against a new `_tags_factory`. Existing handlers that need a second repo instantiate it inline (see Task 7).

- [ ] **Step 1: Add the `_tags_factory` shim**

Near `_categories_factory` / `_triage_factory` (~line 825):

```python
def _tags_factory() -> Any:
    return create_default_tags_repository()
```

Add the import at the top of the file: `from collector.curation import create_default_tags_repository` (or wherever `create_default_categories_repository` is imported from).

- [ ] **Step 2: Write failing tests for tag vocabulary routes**

Add to `tests/unit/test_curation_handler.py`:

```python
def test_create_tag_returns_201() -> None:
    event = _make_event(
        method="POST", path="/tags",
        user_id="u1", body={"name": "Vocal", "color": "#ff8800"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["name"] == "Vocal"
    assert body["color"] == "#ff8800"
    assert "id" in body


def test_create_tag_400_on_invalid_color() -> None:
    event = _make_event(
        method="POST", path="/tags",
        user_id="u1", body={"name": "Vocal", "color": "blue"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "invalid_color"


def test_create_tag_409_on_duplicate_name(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.create_tag.side_effect = TagNameConflictError(
        "Tag with this name already exists"
    )
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: fake_tags,
    )
    event = _make_event(
        method="POST", path="/tags",
        user_id="u1", body={"name": "Vocal", "color": "#ff8800"},
    )
    resp = lambda_handler(event, context=_ctx())
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 409
    assert body["error_code"] == "tag_name_conflict"


def test_list_tags_returns_items_total(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.list_tags.return_value = PaginatedResult(
        items=[
            TagRow(id="tg1", name="Vocal", color="#ff8800",
                   created_at="2026-05-11T12:00:00Z",
                   updated_at="2026-05-11T12:00:00Z"),
        ],
        total=1, limit=20, offset=0,
    )
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: fake_tags,
    )
    event = _make_event(method="GET", path="/tags", user_id="u1")
    resp = lambda_handler(event, context=_ctx())
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == "tg1"


def test_patch_tag_404_when_missing(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.rename_tag.side_effect = TagNotFoundError()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: fake_tags,
    )
    event = _make_event(
        method="PATCH", path="/tags/missing",
        user_id="u1", body={"name": "X"},
        path_params={"tag_id": "missing"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error_code"] == "tag_not_found"


def test_delete_tag_returns_204(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.delete_tag.return_value = True
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: fake_tags,
    )
    event = _make_event(
        method="DELETE", path="/tags/tg1",
        user_id="u1", path_params={"tag_id": "tg1"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 204
    fake_tags.delete_tag.assert_called_once_with(user_id="u1", tag_id="tg1")


def test_delete_tag_404_when_missing(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.delete_tag.return_value = False
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: fake_tags,
    )
    event = _make_event(
        method="DELETE", path="/tags/missing",
        user_id="u1", path_params={"tag_id": "missing"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 404
```

Use the existing test conventions in this file (look for the `_make_event` helper, the `_FakeDataAPI` pattern, or however the file mocks the repos — match it precisely). Do not invent new infrastructure.

- [ ] **Step 3: Add the four handlers + register routes**

Implement four handler functions. Each takes `(event, repo, user_id, correlation_id)` — `repo` here is the `TagsRepository` returned by `_tags_factory`. Repository exceptions (`TagNameConflictError`, `TagNotFoundError`) propagate up to the central `_curation_error_response` mapper at line 100 — no per-handler try/except needed.

```python
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAX_TAG_NAME = 64


def _normalize_tag_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _tag_dict(row) -> dict:
    return {
        "id": row.id, "name": row.name, "color": row.color,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _handle_create_tag(event, repo, user_id, correlation_id):
    body = _parse_body(event)
    name_raw = body.get("name")
    color = body.get("color")
    if not isinstance(name_raw, str):
        raise InvalidTagNameError("name is required")
    name = name_raw.strip()
    if not name or len(name) > _MAX_TAG_NAME:
        raise InvalidTagNameError("name must be 1..64 chars")
    if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
        raise InvalidTagColorError("color must be #RRGGBB hex")
    row = repo.create_tag(
        user_id=user_id,
        tag_id=str(uuid.uuid4()),
        name=name,
        normalized_name=_normalize_tag_name(name),
        color=color,
        now=utc_now(),
    )
    return _json_response(201, _tag_dict(row), correlation_id)


def _handle_list_tags(event, repo, user_id, correlation_id):
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")
    page = repo.list_tags(user_id=user_id, limit=limit, offset=offset, search=search)
    return _json_response(200, {
        "items": [_tag_dict(r) for r in page.items],
        "total": page.total,
        "limit": page.limit,
        "offset": page.offset,
    }, correlation_id)


def _handle_rename_tag(event, repo, user_id, correlation_id):
    tag_id = (event.get("pathParameters") or {}).get("tag_id")
    if not tag_id:
        raise ValidationError("tag_id is required in path")
    body = _parse_body(event)
    name = body.get("name")
    color = body.get("color")
    normalized = None
    if name is not None:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > _MAX_TAG_NAME:
            raise InvalidTagNameError("name must be 1..64 chars")
        name = name.strip()
        normalized = _normalize_tag_name(name)
    if color is not None:
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            raise InvalidTagColorError("color must be #RRGGBB hex")
    if name is None and color is None:
        raise InvalidTagPayloadError("at least one of name|color required")
    row = repo.rename_tag(
        user_id=user_id, tag_id=tag_id,
        name=name, normalized_name=normalized, color=color, now=utc_now(),
    )
    return _json_response(200, _tag_dict(row), correlation_id)


def _handle_delete_tag(event, repo, user_id, correlation_id):
    tag_id = (event.get("pathParameters") or {}).get("tag_id")
    if not tag_id:
        raise ValidationError("tag_id is required in path")
    ok = repo.delete_tag(user_id=user_id, tag_id=tag_id)
    if not ok:
        raise TagNotFoundError()
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }
```

Notes:
- `InvalidTagNameError`, `InvalidTagColorError`, `InvalidTagPayloadError` are added in Task 0. They are `BadQueryParamError` subclasses that override `error_code` so the central responder emits the spec-mandated envelopes (`invalid_name`/`invalid_color`/`invalid_payload`) instead of the generic `bad_query_param`. No per-handler try/except.

Then add to `_ROUTE_TABLE` (`curation_handler.py` ~line 833), as `dict["METHOD /path", (handler, factory)]` entries — matching the existing pattern verbatim:

```python
"POST   /tags":             (_handle_create_tag, _tags_factory),
"GET    /tags":             (_handle_list_tags,  _tags_factory),
"PATCH  /tags/{tag_id}":    (_handle_rename_tag, _tags_factory),
"DELETE /tags/{tag_id}":    (_handle_delete_tag, _tags_factory),
```

(Use exactly the same spacing as the surrounding rows — the table is alignment-formatted.)

- [ ] **Step 4: Run handler tests**

Run: `pytest tests/unit/test_curation_handler.py -q`
Expected: all green (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py src/collector/curation/__init__.py tests/unit/test_curation_handler.py
git commit -m "feat(curation): add tag vocabulary HTTP routes"
```

---

## Task 7: Handler routes for track tags + filter param

**Files:**
- Modify: `src/collector/curation_handler.py`
- Modify: `tests/unit/test_curation_handler.py`

> **Cross-repo handlers.** `_handle_set_track_tags`, `_handle_add_track_tag`, `_handle_remove_track_tag`, `_handle_list_track_tags` all use `_tags_factory` (single repo per route). The two existing handlers that need both `cat_repo` and `tags_repo` — `_handle_list_tracks` and `_handle_remove_track` — keep `_categories_factory` as their primary repo, and call `create_default_tags_repository()` inline within the handler body. This mirrors `_finalize_triage_block` (`curation_handler.py:763`), which already calls `create_default_categories_repository()` inline.

- [ ] **Step 1: Write failing tests**

```python
def _patch_tags(monkeypatch, fake_tags) -> None:
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: fake_tags,
    )


def test_put_track_tags_422_when_not_in_any_category(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.set_track_tags.side_effect = TrackNotInAnyCategoryError(
        "Track not in any category"
    )
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="PUT", path="/tracks/t1/tags",
        user_id="u1", body={"tag_ids": ["tg1"]},
        path_params={"track_id": "t1"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 422
    assert json.loads(resp["body"])["error_code"] == "track_not_in_any_category"


def test_put_track_tags_clear_all_with_empty_array(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.set_track_tags.return_value = []
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="PUT", path="/tracks/t1/tags",
        user_id="u1", body={"tag_ids": []},
        path_params={"track_id": "t1"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["tags"] == []
    fake_tags.set_track_tags.assert_called_once()
    assert fake_tags.set_track_tags.call_args.kwargs["tag_ids"] == []


def test_put_track_tags_400_too_many(monkeypatch) -> None:
    fake_tags = MagicMock()
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="PUT", path="/tracks/t1/tags",
        user_id="u1", body={"tag_ids": ["x"] * 51},
        path_params={"track_id": "t1"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "too_many_tags"
    fake_tags.set_track_tags.assert_not_called()


def test_put_track_tags_400_duplicates(monkeypatch) -> None:
    fake_tags = MagicMock()
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="PUT", path="/tracks/t1/tags",
        user_id="u1", body={"tag_ids": ["tg1", "tg1"]},
        path_params={"track_id": "t1"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "invalid_tag_ids"


def test_post_track_tag_idempotent_returns_201(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.add_track_tag.return_value = [
        TagRow(id="tg1", name="Vocal", color="#f00",
               created_at="2026-05-11T12:00:00Z",
               updated_at="2026-05-11T12:00:00Z"),
    ]
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="POST", path="/tracks/t1/tags",
        user_id="u1", body={"tag_id": "tg1"},
        path_params={"track_id": "t1"},
    )
    resp = lambda_handler(event, context=_ctx())
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 201
    assert body["tags"][0]["id"] == "tg1"


def test_delete_track_tag_returns_204(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.remove_track_tag.return_value = True
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="DELETE", path="/tracks/t1/tags/tg1",
        user_id="u1",
        path_params={"track_id": "t1", "tag_id": "tg1"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 204
    fake_tags.remove_track_tag.assert_called_once_with(
        user_id="u1", track_id="t1", tag_id="tg1",
    )


def test_list_track_tags_returns_array(monkeypatch) -> None:
    fake_tags = MagicMock()
    fake_tags.list_tags_for_tracks.return_value = {
        "t1": [TrackTagRow(track_id="t1", tag_id="tg1", name="Vocal", color="#f00")]
    }
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="GET", path="/tracks/t1/tags",
        user_id="u1", path_params={"track_id": "t1"},
    )
    resp = lambda_handler(event, context=_ctx())
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["tags"] == [{"id": "tg1", "name": "Vocal", "color": "#f00"}]


def test_get_category_tracks_with_tag_filter_passes_params_to_repo(monkeypatch) -> None:
    fake_cat = MagicMock()
    fake_cat.list_tracks.return_value = PaginatedResult(
        items=[], total=0, limit=20, offset=0,
    )
    fake_tags = MagicMock()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="GET", path="/categories/c1/tracks",
        user_id="u1",
        path_params={"id": "c1"},
        query={"tags": "tg1,tg2", "match": "all"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 200
    kwargs = fake_cat.list_tracks.call_args.kwargs
    assert kwargs["tag_ids"] == ["tg1", "tg2"]
    assert kwargs["tag_match"] == "all"
    assert kwargs["tags_repo"] is fake_tags


def test_get_category_tracks_invalid_match_returns_400(monkeypatch) -> None:
    fake_cat = MagicMock()
    fake_tags = MagicMock()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    _patch_tags(monkeypatch, fake_tags)
    event = _make_event(
        method="GET", path="/categories/c1/tracks",
        user_id="u1",
        path_params={"id": "c1"},
        query={"tags": "tg1", "match": "xor"},
    )
    resp = lambda_handler(event, context=_ctx())
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "invalid_match"
```

- [ ] **Step 2: Implement the four track-tag handlers**

All four take `(event, repo, user_id, correlation_id)` where `repo` is the `TagsRepository` from `_tags_factory`. Repository exceptions propagate to the central `_curation_error_response` mapper.

`InvalidTagIdsError`, `TooManyTagsError`, `InvalidMatchError` are already added in Task 0 and importable from `collector.curation`.

```python
def _track_tag_dict(row) -> dict:
    return {"id": row.tag_id, "name": row.name, "color": row.color}


def _handle_list_track_tags(event, repo, user_id, correlation_id):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    grouped = repo.list_tags_for_tracks(user_id=user_id, track_ids=[track_id])
    items = grouped.get(track_id, [])
    return _json_response(
        200, {"tags": [_track_tag_dict(r) for r in items]}, correlation_id,
    )


def _handle_set_track_tags(event, repo, user_id, correlation_id):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    body = _parse_body(event)
    tag_ids = body.get("tag_ids")
    if not isinstance(tag_ids, list):
        raise InvalidTagIdsError("tag_ids must be an array")
    if len(tag_ids) > 50:
        raise TooManyTagsError("Maximum 50 tags per track")
    if any(not isinstance(t, str) or not t for t in tag_ids):
        raise InvalidTagIdsError("tag_ids must be non-empty strings")
    if len(set(tag_ids)) != len(tag_ids):
        raise InvalidTagIdsError("Duplicate tag ids")
    out = repo.set_track_tags(
        user_id=user_id, track_id=track_id, tag_ids=tag_ids, now=utc_now(),
    )
    return _json_response(
        200, {"tags": [_tag_dict(r) for r in out]}, correlation_id,
    )


def _handle_add_track_tag(event, repo, user_id, correlation_id):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    body = _parse_body(event)
    tag_id = body.get("tag_id")
    if not isinstance(tag_id, str) or not tag_id:
        raise InvalidTagIdsError("tag_id required")
    out = repo.add_track_tag(
        user_id=user_id, track_id=track_id, tag_id=tag_id, now=utc_now(),
    )
    return _json_response(
        201, {"tags": [_tag_dict(r) for r in out]}, correlation_id,
    )


def _handle_remove_track_tag(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    track_id = pp.get("track_id")
    tag_id = pp.get("tag_id")
    if not track_id or not tag_id:
        raise ValidationError("track_id and tag_id are required in path")
    repo.remove_track_tag(user_id=user_id, track_id=track_id, tag_id=tag_id)
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }
```

Register in `_ROUTE_TABLE`:

```python
"GET    /tracks/{track_id}/tags":             (_handle_list_track_tags,   _tags_factory),
"PUT    /tracks/{track_id}/tags":             (_handle_set_track_tags,    _tags_factory),
"POST   /tracks/{track_id}/tags":             (_handle_add_track_tag,     _tags_factory),
"DELETE /tracks/{track_id}/tags/{tag_id}":    (_handle_remove_track_tag,  _tags_factory),
```

(Mirror existing row alignment.)

- [ ] **Step 3: Extend `_handle_list_tracks` to parse `tags` + `match` and inline-instantiate `tags_repo`**

Modify the existing `_handle_list_tracks` (`curation_handler.py:403`). The handler keeps `_categories_factory` (so the primary `repo` arg is still `cat_repo`). Inside the body:

```python
qs = event.get("queryStringParameters") or {}
tags_raw = qs.get("tags")
tag_ids = [t for t in (tags_raw.split(",") if tags_raw else []) if t] or None
tag_match = (qs.get("match") or "all").lower()
if tag_match not in ("all", "any"):
    raise InvalidMatchError("match must be 'all' or 'any'")

tags_repo = create_default_tags_repository()
if tags_repo is None:
    # Same defensive guard as `_finalize_triage_block` for `cat_repo is None`.
    return _error(503, "db_not_configured", "Database not configured", correlation_id)

result = repo.list_tracks(
    user_id=user_id, category_id=cid,
    limit=limit, offset=offset, search=search,
    sort=sort, order=order,
    tag_ids=tag_ids, tag_match=tag_match, tags_repo=tags_repo,
)
```

The `_track_in_category_response` serializer was already extended in Task 5 — `tags` is included in every track row.

- [ ] **Step 4: Pass `tags_repo` through `_handle_remove_track`**

Modify `_handle_remove_track` (`curation_handler.py:457`) — the handler keeps `_categories_factory` as its factory. Add inline lookup:

```python
def _handle_remove_track(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    cid = pp.get("id")
    tid = pp.get("track_id")
    if not cid or not tid:
        raise ValidationError("id and track_id are required in path")
    tags_repo = create_default_tags_repository()
    if tags_repo is None:
        return _error(503, "db_not_configured", "Database not configured", correlation_id)
    deleted = repo.remove_track(
        user_id=user_id, category_id=cid, track_id=tid,
        tags_repo=tags_repo,
    )
    if not deleted:
        raise NotFoundError("track_not_in_category", "Track not in category")
    # … existing log_event + 204 return unchanged.
```

Same inline pattern for `_handle_soft_delete` — add a `tags_repo = create_default_tags_repository()` lookup and pass it to `repo.soft_delete(..., tags_repo=tags_repo)`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_curation_handler.py -q`
Expected: all green.

- [ ] **Step 6: Run full unit suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_handler.py
git commit -m "feat(curation): add track-tag HTTP routes and filter param"
```

---

## Task 8: OpenAPI route table

**Files:**
- Modify: `scripts/generate_openapi.py`
- Modify: `docs/openapi.yaml` (generated)

- [ ] **Step 1: Add the new routes to `ROUTES`**

`grep -n "ROUTES" scripts/generate_openapi.py` → find the table. Append entries for each path documented in the spec:

- `POST /tags`, `GET /tags`, `PATCH /tags/{tag_id}`, `DELETE /tags/{tag_id}`
- `GET /tracks/{track_id}/tags`, `PUT /tracks/{track_id}/tags`, `POST /tracks/{track_id}/tags`, `DELETE /tracks/{track_id}/tags/{tag_id}`
- Update the existing entry for `GET /categories/{id}/tracks` to mention the new `tags` and `match` query parameters.

Match the existing `ROUTES` row structure precisely — most rows look like `("METHOD", "/path", summary, request_schema, response_schema, ...)`. Open one nearby row and mimic.

- [ ] **Step 2: Regenerate `docs/openapi.yaml`**

Run:
```
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
```
Expected: file modified, no errors.

- [ ] **Step 3: Sanity-check the regenerated file**

`grep -n "tags:" docs/openapi.yaml | head` — confirm new operation IDs appear.

- [ ] **Step 4: Commit**

```bash
git add scripts/generate_openapi.py docs/openapi.yaml
git commit -m "docs(openapi): document tag vocabulary and track-tag routes"
```

---

## Task 9: Final integration smoke (optional, recommended)

**Files:**
- Create: `tests/integration/test_tags_e2e.py`

- [ ] **Step 1: Skim existing integration tests for the harness pattern**

`grep -rn "def test_" tests/integration/ | head` — pick a fixture set (likely `pg_fixture`, `apply_migrations`).

- [ ] **Step 2: Write a single end-to-end flow**

A track that has no category cannot be tagged → 422.
Add it to a category → PUT tags → GET returns them → filter the categories list by one tag → remove the track from the category → tag rows for that track are gone.

Skeleton:

```python
def test_tag_full_lifecycle(pg_session, fake_user):
    # 1) create tag (HTTP-style POST through lambda_handler)
    # 2) try PUT /tracks/{id}/tags -> 422
    # 3) categories.add_track
    # 4) PUT /tracks/{id}/tags [tag1, tag2] -> 200
    # 5) GET /categories/{cat}/tracks?tags=<tag1> -> contains the track
    # 6) categories.remove_track
    # 7) GET /tracks/{id}/tags -> []
```

- [ ] **Step 3: Run**

Run: `pytest tests/integration/test_tags_e2e.py -q`
Expected: pass against a live local Postgres.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_tags_e2e.py
git commit -m "test(curation): integration smoke for track-tag lifecycle"
```

---

## Final verification

- [ ] **Run full test suite**

Run: `pytest -q`
Expected: green.

- [ ] **Run alembic round-trip locally**

```
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic downgrade -1
alembic upgrade head
```
Expected: both clean.

- [ ] **Skim `git log --oneline` for the branch**

Expected: 8–9 commits, each a single coherent slice, all Conventional-Commits-shaped.
