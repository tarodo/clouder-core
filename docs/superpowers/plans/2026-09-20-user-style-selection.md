# Per-user style selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each user pick the styles they work in, so only those appear in every style dropdown, in an order they control.

**Architecture:** A new `clouder_user_style_prefs` table holds the selection (user_id, style_id, position). `GET /styles` becomes personal — it returns the user's selection ordered by `position`, or the whole catalog when the selection is empty. `?scope=all` returns the catalog annotated with `selected`/`position` for the profile UI and admin screens. `PUT /me/styles` replaces the whole selection in one idempotent call.

**Tech Stack:** Python 3.12 Lambda + Aurora Data API (no psycopg at runtime), Alembic, API Gateway HTTP API (Terraform), React 19 + Mantine 9 + TanStack Query + dnd-kit, pytest, vitest (+ `@vitest/browser`).

**Spec:** `docs/superpowers/specs/2026-09-20-user-style-selection-design.md`

## Global Constraints

- **Runtime DB access is the RDS Data API only.** Never import `psycopg` from any `src/collector/` handler path.
- **`PYTHONPATH=src`** is required for any script outside `pytest`.
- **Use `.venv/bin/python`** for project scripts (Homebrew `python3` lacks `yaml`/`pydantic`). In a worktree, `.venv` lives at the main repo root.
- **A new API route must be registered in three places** or it 404s at the gateway: `src/collector/handler.py` dispatch, `scripts/generate_openapi.py:ROUTES`, `infra/api_gateway.tf`.
- **`log_event` silently drops fields not in `ALLOWED_LOG_FIELDS`.** The fields used in this plan (`user_id`, `style_id`, `item_count`, `correlation_id`) are all allowed.
- **Commits:** Conventional Commits, subject ≤50 chars, no AI-attribution trailer. Branch is `feat/user-style-selection`.
- **Pagination cap:** `_parse_pagination_params` rejects `limit > 200`. Never request more.
- **dnd-kit lists** must use `DragOverlay` + `dropAnimation={null}` + `animateLayoutChanges={() => false}`.
- **Frontend CI gates**, run before merge: `pnpm typecheck`, `pnpm lint`, `pnpm test` (from `frontend/`).

## File Structure

**Backend**

| File | Responsibility |
|---|---|
| `alembic/versions/20260920_32_user_style_prefs.py` (create) | The table + index. |
| `src/collector/db_models.py` (modify) | `UserStylePref` ORM model, for schema parity only. |
| `src/collector/user_styles/__init__.py` (create) | Package marker. |
| `src/collector/user_styles/repository.py` (create) | All SQL for the selection: reads, catalog projection, replace. |
| `src/collector/user_styles/routes.py` (create) | HTTP shape: auth, scope, validation, `(status, body)` tuples. |
| `src/collector/handler.py` (modify) | Dispatch `GET /styles` + `PUT /me/styles` to the new package. |
| `src/collector/repositories.py` (modify) | Delete `list_styles` / `count_styles` (their logic moves). |

**Infra / contract**

| File | Responsibility |
|---|---|
| `infra/api_gateway.tf` (modify) | `PUT /me/styles` route. |
| `scripts/generate_openapi.py` (modify) | `/styles` gains `scope`; new `PUT /me/styles`. |
| `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts` (generated) | Regenerated, never hand-edited. |

**Frontend**

| File | Responsibility |
|---|---|
| `frontend/src/hooks/useAllStyles.ts` (create) | Catalog query (`?scope=all`). |
| `frontend/src/hooks/useUpdateMyStyles.ts` (create) | Debounced `PUT`, cache invalidation. |
| `frontend/src/features/profile/components/MyStylesSection.tsx` (create) | The section: selected list + add list. |
| `frontend/src/features/profile/components/SelectedStyleRow.tsx` (create) | One sortable row. |
| `frontend/src/routes/profile.tsx` (modify) | Layout + mount the section. |
| `frontend/src/i18n/en.json` (modify) | `profile.styles.*` strings. |
| `frontend/src/features/admin/routes/AdminEnrichmentBacklogPage.tsx`, `AdminArtistEnrichmentBacklogPage.tsx` (modify) | Switch to `useAllStyles()`. |

---

### Task 1: Migration + ORM model

**Files:**
- Create: `alembic/versions/20260920_32_user_style_prefs.py`
- Modify: `src/collector/db_models.py`
- Test: `tests/unit/test_migration_32_sql.py`

**Interfaces:**
- Consumes: nothing.
- Produces: table `clouder_user_style_prefs(user_id, style_id, position, updated_at)`; alembic revision `20260920_32` on top of head `20260621_31`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_32_sql.py`:

```python
"""Test that the user style prefs migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path("alembic/versions/20260920_32_user_style_prefs.py")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("mig32", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260920_32"
    assert mig.down_revision == "20260621_31"


def test_upgrade_creates_user_style_prefs() -> None:
    src = _PATH.read_text()
    assert 'create_table(\n        "clouder_user_style_prefs"' in src
    assert "pk_user_style_prefs" in src
    assert "idx_user_style_prefs_user_position" in src
    assert "ck_user_style_prefs_position_nonneg" in src
    # Both FKs cascade: dropping a user or a style must not strand pref rows.
    assert src.count('ondelete="CASCADE"') == 2


def test_downgrade_drops_everything() -> None:
    src = _PATH.read_text()
    assert 'drop_index(\n        "idx_user_style_prefs_user_position"' in src
    assert 'drop_table("clouder_user_style_prefs")' in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_migration_32_sql.py -v`
Expected: FAIL — `FileNotFoundError` / `spec_from_file_location` returns `None`.

- [ ] **Step 3: Write the migration**

Create `alembic/versions/20260920_32_user_style_prefs.py`:

```python
"""user style selection

Revision ID: 20260920_32
Revises: 20260621_31
Create Date: 2026-09-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260920_32"
down_revision = "20260621_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_user_style_prefs",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("style_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "style_id", name="pk_user_style_prefs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_user_style_prefs_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["style_id"], ["clouder_styles.id"],
            name="fk_user_style_prefs_style",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_user_style_prefs_position_nonneg"
        ),
    )
    op.create_index(
        "idx_user_style_prefs_user_position",
        "clouder_user_style_prefs",
        ["user_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_style_prefs_user_position",
        table_name="clouder_user_style_prefs",
    )
    op.drop_table("clouder_user_style_prefs")
```

- [ ] **Step 4: Add the ORM model**

In `src/collector/db_models.py`, after the `User` class, add:

```python
class UserStylePref(Base):
    __tablename__ = "clouder_user_style_prefs"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "style_id", name="pk_user_style_prefs"),
        Index("idx_user_style_prefs_user_position", "user_id", "position"),
        CheckConstraint(
            "position >= 0", name="ck_user_style_prefs_position_nonneg"
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    style_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clouder_styles.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

`PrimaryKeyConstraint`, `Index`, `CheckConstraint`, `ForeignKey`, `String`, `Integer`, `DateTime` and `Mapped`/`mapped_column` are already imported in that file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_migration_32_sql.py -v`
Expected: 3 passed.

- [ ] **Step 6: Verify the migration applies against a local Postgres**

Run:
```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```
Expected: no errors; the up/down/up cycle proves `downgrade()` is correct.
If no local Postgres is running, note it and move on — CI covers it.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/20260920_32_user_style_prefs.py src/collector/db_models.py tests/unit/test_migration_32_sql.py
git commit -m "feat(styles): add user style prefs table"
```

---

### Task 2: Repository reads

**Files:**
- Create: `src/collector/user_styles/__init__.py`, `src/collector/user_styles/repository.py`
- Test: `tests/unit/test_user_styles_repository.py`

**Interfaces:**
- Consumes: `DataAPIClient.execute(sql, params, transaction_id=None) -> list[dict]` from `src/collector/data_api.py`.
- Produces: `UserStylesRepository(data_api)` with
  `count_selection(user_id: str) -> int`,
  `list_for_user(*, user_id: str, limit: int, offset: int, search: str | None) -> list[dict]`,
  `count_for_user(*, user_id: str, search: str | None) -> int`,
  `list_all(*, limit: int, offset: int, search: str | None) -> list[dict]`,
  `count_all(search: str | None) -> int`,
  `list_catalog(*, user_id: str, limit: int, offset: int, search: str | None) -> list[dict]`,
  and module constant `MAX_SELECTION = 100`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_user_styles_repository.py`:

```python
"""UserStylesRepository: per-user style selection reads."""

from __future__ import annotations

from typing import Any

from collector.user_styles.repository import UserStylesRepository


class FakeDataApi:
    """Minimal stub: records (sql, params) per call, returns scripted rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.scripted: list[list[dict[str, Any]]] = []

    def script(self, *batches: list[dict[str, Any]]) -> None:
        self.scripted.extend(batches)

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        transaction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((sql, dict(params or {})))
        if self.scripted:
            return self.scripted.pop(0)
        return []


def test_count_selection_counts_pref_rows_only():
    api = FakeDataApi()
    api.script([{"cnt": 3}])
    repo = UserStylesRepository(data_api=api)

    assert repo.count_selection("u-1") == 3

    sql, params = api.calls[0]
    assert "FROM clouder_user_style_prefs" in sql
    assert params == {"user_id": "u-1"}


def test_list_for_user_joins_and_orders_by_position():
    api = FakeDataApi()
    api.script([{"id": "sty-1", "name": "Drum & Bass"}])
    repo = UserStylesRepository(data_api=api)

    rows = repo.list_for_user(user_id="u-1", limit=50, offset=0, search=None)

    assert rows == [{"id": "sty-1", "name": "Drum & Bass"}]
    sql, params = api.calls[0]
    assert "JOIN clouder_styles s ON s.id = p.style_id" in sql
    assert "ORDER BY p.position" in sql
    assert params == {"user_id": "u-1", "limit": 50, "offset": 0}


def test_list_for_user_applies_search_lowercased():
    api = FakeDataApi()
    repo = UserStylesRepository(data_api=api)

    repo.list_for_user(user_id="u-1", limit=10, offset=0, search="DnB")

    sql, params = api.calls[0]
    assert "s.normalized_name LIKE :search" in sql
    assert params["search"] == "%dnb%"


def test_list_all_keeps_created_at_desc_order():
    api = FakeDataApi()
    repo = UserStylesRepository(data_api=api)

    repo.list_all(limit=50, offset=0, search=None)

    sql, _ = api.calls[0]
    assert "FROM clouder_styles" in sql
    assert "ORDER BY created_at DESC" in sql
    assert "clouder_user_style_prefs" not in sql


def test_list_catalog_projects_selected_and_position():
    api = FakeDataApi()
    api.script([
        {"id": "sty-1", "name": "Drum & Bass", "selected": True, "position": 0},
        {"id": "sty-2", "name": "House", "selected": False, "position": None},
    ])
    repo = UserStylesRepository(data_api=api)

    rows = repo.list_catalog(user_id="u-1", limit=200, offset=0, search=None)

    assert rows[0]["selected"] is True
    assert rows[1]["position"] is None
    sql, params = api.calls[0]
    assert "LEFT JOIN clouder_user_style_prefs p" in sql
    assert "ORDER BY (p.position IS NULL), p.position, s.name" in sql
    assert params["user_id"] == "u-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_user_styles_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.user_styles'`.

- [ ] **Step 3: Create the package and the read methods**

Create empty `src/collector/user_styles/__init__.py`.

Create `src/collector/user_styles/repository.py`:

```python
"""Aurora Data API persistence for per-user style selection."""

from __future__ import annotations

from typing import Any

MAX_SELECTION = 100

_STYLE_COLUMNS = "s.id, s.name, s.normalized_name, s.created_at, s.updated_at"


class UserStylesRepository:
    def __init__(self, data_api: Any) -> None:
        self._data_api = data_api

    # ── reads ────────────────────────────────────────────────────────
    def count_selection(self, user_id: str) -> int:
        rows = self._data_api.execute(
            """
            SELECT count(*) AS cnt FROM clouder_user_style_prefs
            WHERE user_id = :user_id
            """,
            {"user_id": user_id},
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_for_user(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "user_id": user_id, "limit": limit, "offset": offset,
        }
        where = ""
        if search:
            where = " AND s.normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT {_STYLE_COLUMNS}
            FROM clouder_user_style_prefs p
            JOIN clouder_styles s ON s.id = p.style_id
            WHERE p.user_id = :user_id{where}
            ORDER BY p.position
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_for_user(
        self, *, user_id: str, search: str | None = None
    ) -> int:
        params: dict[str, Any] = {"user_id": user_id}
        where = ""
        if search:
            where = " AND s.normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"""
            SELECT count(*) AS cnt
            FROM clouder_user_style_prefs p
            JOIN clouder_styles s ON s.id = p.style_id
            WHERE p.user_id = :user_id{where}
            """,
            params,
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_all(
        self, *, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        """Catalog in legacy order — the empty-selection fallback."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT id, name, normalized_name, created_at, updated_at
            FROM clouder_styles
            {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_all(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_styles {where}", params
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_catalog(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """Whole catalog annotated with the caller's selection."""
        params: dict[str, Any] = {
            "user_id": user_id, "limit": limit, "offset": offset,
        }
        where = ""
        if search:
            where = "WHERE s.normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT {_STYLE_COLUMNS},
                   (p.user_id IS NOT NULL) AS selected,
                   p.position AS position
            FROM clouder_styles s
            LEFT JOIN clouder_user_style_prefs p
                   ON p.style_id = s.id AND p.user_id = :user_id
            {where}
            ORDER BY (p.position IS NULL), p.position, s.name
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_user_styles_repository.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/user_styles/ tests/unit/test_user_styles_repository.py
git commit -m "feat(styles): add user styles repository reads"
```

---

### Task 3: Repository write — `replace_selection`

**Files:**
- Modify: `src/collector/user_styles/repository.py`
- Test: `tests/unit/test_user_styles_repository.py`

**Interfaces:**
- Consumes: `UserStylesRepository` from Task 2; `DataAPIClient.transaction()` context manager yielding `transaction_id`; `ValidationError` from `src/collector/errors.py`.
- Produces: `replace_selection(*, user_id: str, style_ids: Sequence[str], now: datetime | None = None) -> None`, raising `ValidationError("unknown style_id: <id>")`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_user_styles_repository.py`:

```python
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from collector.errors import ValidationError


class FakeTxDataApi(FakeDataApi):
    """FakeDataApi plus a transaction() context manager."""

    def __init__(self) -> None:
        super().__init__()
        self.committed = False

    @contextmanager
    def transaction(self):
        yield "tx-1"
        self.committed = True


_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def test_replace_selection_deletes_then_inserts_in_order():
    api = FakeTxDataApi()
    api.script([{"id": "sty-1"}, {"id": "sty-2"}])  # validation SELECT
    repo = UserStylesRepository(data_api=api)

    repo.replace_selection(
        user_id="u-1", style_ids=["sty-2", "sty-1"], now=_NOW
    )

    sqls = [sql for sql, _ in api.calls]
    assert "SELECT id FROM clouder_styles" in sqls[0]
    assert "DELETE FROM clouder_user_style_prefs" in sqls[1]
    assert "INSERT INTO clouder_user_style_prefs" in sqls[2]
    inserted = [params for sql, params in api.calls if "INSERT" in sql]
    assert [(p["style_id"], p["position"]) for p in inserted] == [
        ("sty-2", 0),
        ("sty-1", 1),
    ]
    assert all(p["now"] == _NOW for p in inserted)
    assert api.committed is True


def test_replace_selection_rejects_unknown_style():
    api = FakeTxDataApi()
    api.script([{"id": "sty-1"}])  # sty-9 missing from the catalog
    repo = UserStylesRepository(data_api=api)

    with pytest.raises(ValidationError) as exc:
        repo.replace_selection(
            user_id="u-1", style_ids=["sty-1", "sty-9"], now=_NOW
        )

    assert "unknown style_id: sty-9" in exc.value.message
    assert not any("INSERT" in sql for sql, _ in api.calls)


def test_replace_selection_empty_list_clears_without_validation():
    api = FakeTxDataApi()
    repo = UserStylesRepository(data_api=api)

    repo.replace_selection(user_id="u-1", style_ids=[], now=_NOW)

    sqls = [sql for sql, _ in api.calls]
    assert len(sqls) == 1
    assert "DELETE FROM clouder_user_style_prefs" in sqls[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_user_styles_repository.py -k replace -v`
Expected: FAIL — `AttributeError: 'UserStylesRepository' object has no attribute 'replace_selection'`.

- [ ] **Step 3: Implement `replace_selection`**

In `src/collector/user_styles/repository.py`, extend the imports and add the method:

```python
from datetime import datetime, timezone
from typing import Any, Sequence

from ..errors import ValidationError
```

```python
    # ── write ────────────────────────────────────────────────────────
    def replace_selection(
        self,
        *,
        user_id: str,
        style_ids: Sequence[str],
        now: datetime | None = None,
    ) -> None:
        """Replace the whole selection; array order becomes `position`."""
        at = now or datetime.now(timezone.utc)
        with self._data_api.transaction() as tx_id:
            if style_ids:
                placeholders = ", ".join(
                    f":id_{i}" for i in range(len(style_ids))
                )
                params = {
                    f"id_{i}": sid for i, sid in enumerate(style_ids)
                }
                rows = self._data_api.execute(
                    f"SELECT id FROM clouder_styles WHERE id IN ({placeholders})",
                    params,
                    transaction_id=tx_id,
                )
                known = {r["id"] for r in rows}
                for sid in style_ids:
                    if sid not in known:
                        raise ValidationError(f"unknown style_id: {sid}")

            self._data_api.execute(
                "DELETE FROM clouder_user_style_prefs WHERE user_id = :user_id",
                {"user_id": user_id},
                transaction_id=tx_id,
            )
            for idx, sid in enumerate(style_ids):
                self._data_api.execute(
                    """
                    INSERT INTO clouder_user_style_prefs
                        (user_id, style_id, position, updated_at)
                    VALUES (:user_id, :style_id, :position, :now)
                    """,
                    {
                        "user_id": user_id,
                        "style_id": sid,
                        "position": idx,
                        "now": at,
                    },
                    transaction_id=tx_id,
                )
```

Raising inside the `with` block aborts the transaction — `DataAPIClient.transaction()` rolls back on any exception, so a bad id leaves the old selection intact.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_user_styles_repository.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/user_styles/repository.py tests/unit/test_user_styles_repository.py
git commit -m "feat(styles): replace user style selection in one tx"
```

---

### Task 4: `GET /styles` routes through the new package

**Files:**
- Create: `src/collector/user_styles/routes.py`
- Modify: `src/collector/handler.py` (remove `"GET /styles"` from `_LIST_ROUTES` at line 57, add dispatch in `_route`), `src/collector/repositories.py` (delete `list_styles` at 1119 and `count_styles` at 1138)
- Test: `tests/unit/test_user_styles_routes.py`, `tests/integration/test_handler.py:367`

**Interfaces:**
- Consumes: `UserStylesRepository` (Tasks 2–3); `_parse_pagination_params(event) -> (limit, offset, search)` and `_json_response(status, payload, correlation_id)` from `handler.py`.
- Produces: `handle_get_styles(event, *, limit: int, offset: int, search: str | None) -> tuple[int, dict]`; `_build_repository() -> UserStylesRepository | None` (monkeypatch target in tests); `extract_user_id(event) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_user_styles_routes.py`:

```python
"""GET /styles — personal list, catalog scope, fallbacks."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _user_event(route: str, *, qs: dict | None = None,
                body: dict | None = None) -> dict:
    return {
        "routeKey": route,
        "pathParameters": {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


@pytest.fixture
def fake_repo(monkeypatch):
    repo = MagicMock()
    monkeypatch.setattr(
        "collector.user_styles.routes._build_repository", lambda: repo
    )
    return repo


def test_get_styles_with_selection_returns_personal_list(fake_repo):
    from collector import handler

    fake_repo.count_selection.return_value = 2
    fake_repo.list_for_user.return_value = [{"id": "sty-1", "name": "DnB"}]
    fake_repo.count_for_user.return_value = 2

    resp = handler.lambda_handler(_user_event("GET /styles"), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["items"][0]["name"] == "DnB"
    assert body["total"] == 2
    assert body["correlation_id"]
    fake_repo.list_for_user.assert_called_once_with(
        user_id="u-1", limit=50, offset=0, search=None
    )
    fake_repo.list_all.assert_not_called()


def test_get_styles_without_selection_falls_back_to_catalog(fake_repo):
    from collector import handler

    fake_repo.count_selection.return_value = 0
    fake_repo.list_all.return_value = [{"id": "sty-9", "name": "House"}]
    fake_repo.count_all.return_value = 1

    resp = handler.lambda_handler(_user_event("GET /styles"), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["items"][0]["name"] == "House"
    fake_repo.list_for_user.assert_not_called()


def test_get_styles_scope_all_returns_catalog_with_flags(fake_repo):
    from collector import handler

    fake_repo.list_catalog.return_value = [
        {"id": "sty-1", "name": "DnB", "selected": True, "position": 0}
    ]
    fake_repo.count_all.return_value = 1

    resp = handler.lambda_handler(
        _user_event("GET /styles", qs={"scope": "all"}), None
    )

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["items"][0]["selected"] is True
    fake_repo.count_selection.assert_not_called()


def test_get_styles_rejects_unknown_scope(fake_repo):
    from collector import handler

    resp = handler.lambda_handler(
        _user_event("GET /styles", qs={"scope": "mine"}), None
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "validation_error"


def test_get_styles_without_user_returns_401(monkeypatch):
    from collector import handler

    event = _user_event("GET /styles")
    event["requestContext"] = {"authorizer": {"lambda": {}}}

    resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 401


def test_get_styles_without_db_returns_503(monkeypatch):
    from collector import handler

    monkeypatch.setattr(
        "collector.user_styles.routes._build_repository", lambda: None
    )

    resp = handler.lambda_handler(_user_event("GET /styles"), None)

    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error_code"] == "db_not_configured"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_user_styles_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.user_styles.routes'`.

- [ ] **Step 3: Write the routes module**

Create `src/collector/user_styles/routes.py`:

```python
"""HTTP routes for per-user style selection."""

from __future__ import annotations

from typing import Any, Mapping

from ..data_api import create_default_data_api_client
from ..errors import ValidationError
from ..settings import get_data_api_settings
from .repository import UserStylesRepository

_UNAUTHORIZED = (
    401,
    {"error_code": "unauthorized", "message": "Authentication required"},
)
_NO_DB = (
    503,
    {"error_code": "db_not_configured", "message": "Database is not configured"},
)


def _build_repository() -> UserStylesRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return UserStylesRepository(data_api=client)


def extract_user_id(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if not isinstance(rc, Mapping):
        return None
    authz = rc.get("authorizer")
    if not isinstance(authz, Mapping):
        return None
    ctx = authz.get("lambda")
    if isinstance(ctx, Mapping):
        return ctx.get("user_id")
    return None


def handle_get_styles(
    event: Mapping[str, Any],
    *,
    limit: int,
    offset: int,
    search: str | None,
) -> tuple[int, dict[str, Any]]:
    user_id = extract_user_id(event)
    if not user_id:
        return _UNAUTHORIZED

    qs = event.get("queryStringParameters") or {}
    scope = (qs.get("scope") or "").strip()
    if scope and scope != "all":
        raise ValidationError("scope must be 'all'")

    repo = _build_repository()
    if repo is None:
        return _NO_DB

    if scope == "all":
        items = repo.list_catalog(
            user_id=user_id, limit=limit, offset=offset, search=search
        )
        total = repo.count_all(search)
    elif repo.count_selection(user_id) > 0:
        items = repo.list_for_user(
            user_id=user_id, limit=limit, offset=offset, search=search
        )
        total = repo.count_for_user(user_id=user_id, search=search)
    else:
        items = repo.list_all(limit=limit, offset=offset, search=search)
        total = repo.count_all(search)

    return 200, {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
```

- [ ] **Step 4: Wire it into the handler**

In `src/collector/handler.py`, delete the `"GET /styles"` entry from `_LIST_ROUTES` (line 57) so it reads:

```python
_LIST_ROUTES = {
    "GET /tracks": ("tracks", "list_tracks", "count_tracks"),
    "GET /albums": ("albums", "list_albums", "count_albums"),
}
```

In `_route`, next to the other per-route dispatches, add:

```python
    if route_key == "GET /styles":
        from .user_styles.routes import handle_get_styles
        limit, offset, search = _parse_pagination_params(event)
        status, body = handle_get_styles(
            event, limit=limit, offset=offset, search=search
        )
        if status == 200:
            body["correlation_id"] = correlation_id
            log_event(
                "INFO",
                "list_completed",
                correlation_id=correlation_id,
                entity="styles",
                result_count=len(body["items"]),
                total_count=body["total"],
                limit=limit,
                offset=offset,
            )
        return _json_response(status, body, correlation_id)
```

`ValidationError` raised inside (`scope must be 'all'`, bad pagination) is caught by `lambda_handler`'s `AppError` branch and rendered as `400 validation_error`.

- [ ] **Step 5: Delete the superseded repository methods**

In `src/collector/repositories.py`, delete `list_styles` (line 1119) and `count_styles` (line 1138). Nothing else calls them — confirm with:

```bash
grep -rn "list_styles\|count_styles" src tests scripts
```
Expected after the edit: only hits inside `tests/integration/test_handler.py` (fixed in the next step) and `src/collector/user_styles/`.

- [ ] **Step 6: Update the integration test**

In `tests/integration/test_handler.py`, replace `test_list_styles_returns_results` (line 367) with:

```python
def test_list_styles_returns_results(monkeypatch, context) -> None:
    class FakeRepo:
        def count_selection(self, user_id):
            return 1

        def list_for_user(self, *, user_id, limit, offset, search):
            return [
                {
                    "id": "sty-1",
                    "name": "House",
                    "normalized_name": "house",
                    "created_at": "2026-03-01T10:00:00Z",
                    "updated_at": "2026-03-01T10:00:00Z",
                },
            ]

        def count_for_user(self, *, user_id, search):
            return 1

    monkeypatch.setattr(
        "collector.user_styles.routes._build_repository", lambda: FakeRepo()
    )

    response = lambda_handler(_list_event("GET /styles"), context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total"] == 1
    assert body["items"][0]["name"] == "House"
```

`_list_event` (line 305) already carries `authorizer.lambda.user_id == "u"`, so no event surgery is needed.

- [ ] **Step 7: Run the full backend suite**

Run: `pytest -q`
Expected: all pass. A failure in `tests/integration/test_handler.py` means `_list_event` shape differs — inspect and adjust the event, not the route.

- [ ] **Step 8: Commit**

```bash
git add src/collector/user_styles/routes.py src/collector/handler.py src/collector/repositories.py tests/unit/test_user_styles_routes.py tests/integration/test_handler.py
git commit -m "feat(styles): make GET /styles personal"
```

---

### Task 5: `PUT /me/styles`

**Files:**
- Modify: `src/collector/user_styles/routes.py`, `src/collector/handler.py`
- Test: `tests/unit/test_user_styles_routes.py`

**Interfaces:**
- Consumes: `replace_selection` (Task 3), `_build_repository` / `_extract_user_id` (Task 4), `MAX_SELECTION` from `repository.py`.
- Produces: `handle_put_my_styles(event) -> tuple[int, dict]` returning `(204, {})` on success.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_user_styles_routes.py`:

```python
def test_put_my_styles_replaces_selection(fake_repo):
    from collector import handler

    resp = handler.lambda_handler(
        _user_event("PUT /me/styles", body={"style_ids": ["sty-2", "sty-1"]}),
        None,
    )

    assert resp["statusCode"] == 204
    assert resp["body"] == ""
    fake_repo.replace_selection.assert_called_once_with(
        user_id="u-1", style_ids=["sty-2", "sty-1"]
    )


def test_put_my_styles_empty_list_clears(fake_repo):
    from collector import handler

    resp = handler.lambda_handler(
        _user_event("PUT /me/styles", body={"style_ids": []}), None
    )

    assert resp["statusCode"] == 204
    fake_repo.replace_selection.assert_called_once_with(
        user_id="u-1", style_ids=[]
    )


@pytest.mark.parametrize(
    "body,fragment",
    [
        ({}, "style_ids must be an array"),
        ({"style_ids": "sty-1"}, "style_ids must be an array"),
        ({"style_ids": [1, 2]}, "style_ids must be an array"),
        ({"style_ids": ["a", "a"]}, "style_ids must be unique"),
        ({"style_ids": [f"s-{i}" for i in range(101)]}, "exceeds 100"),
    ],
)
def test_put_my_styles_validation(fake_repo, body, fragment):
    from collector import handler

    resp = handler.lambda_handler(_user_event("PUT /me/styles", body=body), None)

    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error_code"] == "validation_error"
    assert fragment in payload["message"]
    fake_repo.replace_selection.assert_not_called()


def test_put_my_styles_unknown_style_returns_400(fake_repo):
    from collector import handler
    from collector.errors import ValidationError

    fake_repo.replace_selection.side_effect = ValidationError(
        "unknown style_id: sty-9"
    )

    resp = handler.lambda_handler(
        _user_event("PUT /me/styles", body={"style_ids": ["sty-9"]}), None
    )

    assert resp["statusCode"] == 400
    assert "unknown style_id: sty-9" in json.loads(resp["body"])["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_user_styles_routes.py -k put -v`
Expected: FAIL — the route is unknown, so the handler returns 404.

- [ ] **Step 3: Implement the route**

In `src/collector/user_styles/routes.py`, add the import and the handler:

```python
import json

from .repository import MAX_SELECTION, UserStylesRepository
```

```python
def handle_put_my_styles(event: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    user_id = extract_user_id(event)
    if not user_id:
        return _UNAUTHORIZED

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")

    style_ids = body.get("style_ids") if isinstance(body, Mapping) else None
    if not isinstance(style_ids, list) or not all(
        isinstance(sid, str) for sid in style_ids
    ):
        raise ValidationError("style_ids must be an array of style ids")
    if len(set(style_ids)) != len(style_ids):
        raise ValidationError("style_ids must be unique")
    if len(style_ids) > MAX_SELECTION:
        raise ValidationError(
            f"style_ids exceeds {MAX_SELECTION} entries"
        )

    repo = _build_repository()
    if repo is None:
        return _NO_DB

    repo.replace_selection(user_id=user_id, style_ids=style_ids)
    return 204, {}
```

- [ ] **Step 4: Wire it into the handler**

In `src/collector/handler.py`, right after the `GET /styles` block:

```python
    if route_key == "PUT /me/styles":
        from .user_styles.routes import extract_user_id, handle_put_my_styles
        status, body = handle_put_my_styles(event)
        if status == 204:
            log_event(
                "INFO",
                "user_styles_updated",
                correlation_id=correlation_id,
                user_id=extract_user_id(event),
            )
            return {
                "statusCode": 204,
                "headers": {"x-correlation-id": correlation_id},
                "body": "",
            }
        return _json_response(status, body, correlation_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_user_styles_routes.py -v`
Expected: 15 passed (6 from Task 4 + 9 here, counting the parametrized cases).

- [ ] **Step 6: Run the full backend suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/collector/user_styles/routes.py src/collector/handler.py tests/unit/test_user_styles_routes.py
git commit -m "feat(styles): add PUT /me/styles"
```

---

### Task 6: Gateway route + OpenAPI + generated client types

**Files:**
- Modify: `infra/api_gateway.tf`, `scripts/generate_openapi.py:2170-2190`
- Generated: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: routes from Tasks 4–5.
- Produces: `PUT /me/styles` reachable through API Gateway; `schema.d.ts` types `paths['/styles']` (with `scope`) and `paths['/me/styles']`.

- [ ] **Step 1: Add the Terraform route**

In `infra/api_gateway.tf`, next to `my_label_preferences` (line 208):

```hcl
resource "aws_apigatewayv2_route" "my_styles_put" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "PUT /me/styles"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Update the OpenAPI route table**

In `scripts/generate_openapi.py`, change the canonical-core loop (line ~2189) to cover only `tracks` and `albums`:

```python
        for entity in ("tracks", "albums")
```

Then add two entries right after that block:

```python
    {
        "method": "get",
        "path": "/styles",
        "auth": AUTH,
        "summary": "List styles (paginated).",
        "description": (
            "Returns the caller's selected styles ordered by their own "
            "position. When the caller has selected nothing, returns the "
            "whole catalog. `scope=all` returns the whole catalog annotated "
            "with `selected` and `position`."
        ),
        "parameters": PAGINATION_PARAMS + [
            {
                "name": "scope",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["all"]},
                "description": "`all` returns the full catalog with selection flags.",
            },
        ],
        "responses": {
            "200": _make_response(200, "Paginated items.", LIST_RESPONSE_TEMPLATE),
            "400": _error(400, "validation_error (limit/offset/scope)."),
            "503": _error(503, "db_not_configured."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "put",
        "path": "/me/styles",
        "auth": AUTH,
        "summary": "Replace the caller's style selection.",
        "description": (
            "Array order becomes the display order. An empty array clears "
            "the selection, which makes every style visible again."
        ),
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "style_ids": {
                        "type": "array",
                        "maxItems": 100,
                        "items": {"type": "string"},
                    },
                },
                "required": ["style_ids"],
                "additionalProperties": False,
            }}},
        },
        "responses": {
            "204": {"description": "Selection replaced."},
            "400": _error(400, "validation_error (shape, duplicates, unknown id)."),
            "503": _error(503, "db_not_configured."),
            **COMMON_AUTH_ERRORS,
        },
    },
```

- [ ] **Step 3: Regenerate the spec and the client types**

Run:
```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
cd frontend && pnpm api:types
```

Expected: `docs/api/openapi.yaml` gains `/me/styles` and the `scope` parameter; `frontend/src/api/schema.d.ts` changes accordingly.

- [ ] **Step 4: Verify Terraform is valid**

Run: `cd infra && terraform validate`
Expected: "Success! The configuration is valid." Do **not** run `terraform apply` — deployment is a separate, manual step.

- [ ] **Step 5: Commit**

```bash
git add infra/api_gateway.tf scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "feat(api): expose PUT /me/styles and styles scope"
```

---

### Task 7: Frontend data hooks

**Files:**
- Create: `frontend/src/hooks/useAllStyles.ts`, `frontend/src/hooks/useUpdateMyStyles.ts`
- Test: `frontend/src/hooks/__tests__/useAllStyles.test.tsx`, `frontend/src/hooks/__tests__/useUpdateMyStyles.test.tsx`

**Interfaces:**
- Consumes: `api` from `frontend/src/api/client.ts`; endpoints from Tasks 4–6.
- Produces:
  - `useAllStyles(): UseQueryResult<PaginatedCatalogStyles>`, `allStylesKey = ['styles', 'all']`, `interface CatalogStyle { id: string; name: string; selected: boolean; position: number | null }`.
  - `useUpdateMyStyles(): { queueSelection(styleIds: string[]): void; flushNow(): Promise<void> }`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/hooks/__tests__/useAllStyles.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { tokenStore } from '../../auth/tokenStore';
import { useAllStyles } from '../useAllStyles';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useAllStyles', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('requests scope=all and exposes selection flags', async () => {
    let seenUrl = '';
    server.use(
      http.get('http://localhost/styles', ({ request }) => {
        seenUrl = request.url;
        return HttpResponse.json({
          items: [
            { id: 's1', name: 'DnB', selected: true, position: 0 },
            { id: 's2', name: 'House', selected: false, position: null },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useAllStyles(), { wrapper: wrap(qc) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seenUrl).toContain('scope=all');
    expect(seenUrl).toContain('limit=200');
    expect(result.current.data?.items[1].position).toBeNull();
  });
});
```

Create `frontend/src/hooks/__tests__/useUpdateMyStyles.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { tokenStore } from '../../auth/tokenStore';
import { useUpdateMyStyles } from '../useUpdateMyStyles';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useUpdateMyStyles', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    vi.useFakeTimers();
  });

  it('coalesces rapid changes into one PUT with the last order', async () => {
    let putCount = 0;
    let lastBody: { style_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/me/styles', async ({ request }) => {
        putCount += 1;
        lastBody = (await request.json()) as { style_ids: string[] };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUpdateMyStyles(), { wrapper: wrap(qc) });

    act(() => result.current.queueSelection(['s1']));
    act(() => result.current.queueSelection(['s1', 's2']));
    act(() => result.current.queueSelection(['s2', 's1']));

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });

    expect(putCount).toBe(1);
    expect(lastBody).toEqual({ style_ids: ['s2', 's1'] });
  });

  it('invalidates both style caches after a successful PUT', async () => {
    server.use(
      http.put('http://localhost/me/styles', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateMyStyles(), { wrapper: wrap(qc) });

    act(() => result.current.queueSelection(['s1']));
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });

    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys.some((k) => k?.includes('"styles"'))).toBe(true);
    expect(keys.some((k) => k?.includes('"all"'))).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm test -- useAllStyles useUpdateMyStyles`
Expected: FAIL — cannot resolve `../useAllStyles`.

- [ ] **Step 3: Write `useAllStyles`**

Create `frontend/src/hooks/useAllStyles.ts`:

```ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../api/client';

export interface CatalogStyle {
  id: string;
  name: string;
  selected: boolean;
  position: number | null;
}

export interface PaginatedCatalogStyles {
  items: CatalogStyle[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export const allStylesKey = ['styles', 'all'] as const;

/** Whole style catalog, annotated with the caller's selection. */
export function useAllStyles(): UseQueryResult<PaginatedCatalogStyles> {
  return useQuery({
    queryKey: allStylesKey,
    queryFn: () =>
      api<PaginatedCatalogStyles>('/styles?scope=all&limit=200&offset=0'),
    staleTime: 5 * 60 * 1000,
  });
}
```

- [ ] **Step 4: Write `useUpdateMyStyles`**

Create `frontend/src/hooks/useUpdateMyStyles.ts` (debounce copied from `features/categories/hooks/useReorderCategories.ts`):

```ts
import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { allStylesKey } from './useAllStyles';

const DEBOUNCE_MS = 200;

export interface UpdateMyStylesHandle {
  queueSelection: (styleIds: string[]) => void;
  flushNow: () => Promise<void>;
}

export function useUpdateMyStyles(): UpdateMyStylesHandle {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const latestRef = useRef<string[] | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const mutation = useMutation<unknown, Error, string[]>({
    mutationFn: (styleIds) =>
      api('/me/styles', {
        method: 'PUT',
        body: JSON.stringify({ style_ids: styleIds }),
      }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['styles'] });
      void qc.invalidateQueries({ queryKey: allStylesKey });
    },
    onError: () => {
      try {
        notifications.show({
          message: t('profile.styles.toast.save_failed'),
          color: 'red',
        });
      } catch {
        // notifications may not be mounted in the test environment
      }
    },
  });

  const flushNow = useCallback(async () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const pending = latestRef.current;
    latestRef.current = null;
    if (pending) await mutation.mutateAsync(pending).catch(() => undefined);
  }, [mutation]);

  const queueSelection = useCallback(
    (styleIds: string[]) => {
      latestRef.current = styleIds;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        void flushNow();
      }, DEBOUNCE_MS);
    },
    [flushNow],
  );

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  return { queueSelection, flushNow };
}
```

Note: `['styles']` invalidation also matches `['styles', 'all']` by prefix; both calls are kept explicit so a future key change cannot silently drop one.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && pnpm test -- useAllStyles useUpdateMyStyles`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useAllStyles.ts frontend/src/hooks/useUpdateMyStyles.ts frontend/src/hooks/__tests__/
git commit -m "feat(web): add style catalog and selection hooks"
```

---

### Task 8: Profile section UI

**Files:**
- Create: `frontend/src/features/profile/components/MyStylesSection.tsx`, `frontend/src/features/profile/components/SelectedStyleRow.tsx`
- Modify: `frontend/src/routes/profile.tsx`, `frontend/src/i18n/en.json`
- Test: `frontend/src/features/profile/components/__tests__/MyStylesSection.test.tsx`

**Interfaces:**
- Consumes: `useAllStyles`, `CatalogStyle`, `useUpdateMyStyles` (Task 7).
- Produces: `<MyStylesSection />` (no props); `<SelectedStyleRow style={CatalogStyle} onRemove={(id: string) => void} />`.

- [ ] **Step 1: Add the i18n strings**

In `frontend/src/i18n/en.json`, add a top-level `profile` block (keep keys alphabetical within the block if the file does):

```json
  "profile": {
    "styles": {
      "title": "My styles",
      "description": "Only these styles appear in style pickers. Drag to reorder — the first one is the default.",
      "empty_hint": "Nothing selected — all styles are visible.",
      "add_placeholder": "Search styles to add",
      "add_title": "Add a style",
      "remove": "Remove from my styles",
      "drag_handle": "Reorder",
      "toast": {
        "save_failed": "Could not save your styles. Try again."
      }
    }
  }
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/features/profile/components/__tests__/MyStylesSection.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { MyStylesSection } from '../MyStylesSection';

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <MyStylesSection />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const catalog = {
  items: [
    { id: 's1', name: 'Drum & Bass', selected: true, position: 0 },
    { id: 's2', name: 'House', selected: false, position: null },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

describe('MyStylesSection', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/styles', () => HttpResponse.json(catalog)),
    );
  });

  it('splits the catalog into selected and addable', async () => {
    renderSection();

    expect(await screen.findByText('Drum & Bass')).toBeDefined();
    expect(screen.getByText('House')).toBeDefined();
    expect(screen.queryByText(/Nothing selected/)).toBeNull();
  });

  it('adding a style PUTs the new selection with it appended', async () => {
    let body: { style_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/me/styles', async ({ request }) => {
        body = (await request.json()) as { style_ids: string[] };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderSection();

    await screen.findByText('House');
    await userEvent.click(screen.getByRole('button', { name: /add House/i }));

    await waitFor(() => expect(body).toEqual({ style_ids: ['s1', 's2'] }));
  });

  it('removing a style PUTs the remainder', async () => {
    let body: { style_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/me/styles', async ({ request }) => {
        body = (await request.json()) as { style_ids: string[] };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderSection();

    await screen.findByText('Drum & Bass');
    await userEvent.click(
      screen.getByRole('button', { name: /remove Drum & Bass/i }),
    );

    await waitFor(() => expect(body).toEqual({ style_ids: [] }));
  });

  it('shows the hint when nothing is selected', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          ...catalog,
          items: catalog.items.map((s) => ({ ...s, selected: false, position: null })),
        }),
      ),
    );
    renderSection();

    expect(await screen.findByText(/Nothing selected/)).toBeDefined();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && pnpm test -- MyStylesSection`
Expected: FAIL — cannot resolve `../MyStylesSection`.

- [ ] **Step 4: Write `SelectedStyleRow`**

Create `frontend/src/features/profile/components/SelectedStyleRow.tsx`:

```tsx
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ActionIcon, Group, Paper, Text } from '@mantine/core';
import { IconGripVertical, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { CatalogStyle } from '../../../hooks/useAllStyles';

export interface SelectedStyleRowProps {
  style: CatalogStyle;
  onRemove: (styleId: string) => void;
  /** True when rendered inside the DragOverlay. */
  overlay?: boolean;
}

export function SelectedStyleRow({ style, onRemove, overlay }: SelectedStyleRowProps) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: style.id, animateLayoutChanges: () => false });

  return (
    <Paper
      ref={overlay ? undefined : setNodeRef}
      withBorder
      p="xs"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: !overlay && isDragging ? 0 : 1,
      }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <ActionIcon
            variant="subtle"
            aria-label={t('profile.styles.drag_handle')}
            {...attributes}
            {...listeners}
          >
            <IconGripVertical size={16} />
          </ActionIcon>
          <Text>{style.name}</Text>
        </Group>
        <ActionIcon
          variant="subtle"
          color="red"
          aria-label={`${t('profile.styles.remove')} ${style.name}`}
          onClick={() => onRemove(style.id)}
        >
          <IconX size={16} />
        </ActionIcon>
      </Group>
    </Paper>
  );
}
```

`frontend/src/components/icons.ts` re-exports `IconX` and `IconPlus` but not
`IconGripVertical`, so this file imports all three straight from
`@tabler/icons-react` — the same choice `CategoryRow.tsx` makes.

- [ ] **Step 5: Write `MyStylesSection`**

Create `frontend/src/features/profile/components/MyStylesSection.tsx`:

```tsx
import { useMemo, useState } from 'react';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { ActionIcon, Group, Loader, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useAllStyles, type CatalogStyle } from '../../../hooks/useAllStyles';
import { useUpdateMyStyles } from '../../../hooks/useUpdateMyStyles';
import { SelectedStyleRow } from './SelectedStyleRow';

export function MyStylesSection() {
  const { t } = useTranslation();
  const { data, isLoading } = useAllStyles();
  const { queueSelection } = useUpdateMyStyles();
  const [draft, setDraft] = useState<string[] | null>(null);
  const [search, setSearch] = useState('');
  const [dragId, setDragId] = useState<string | null>(null);

  const items = useMemo(() => data?.items ?? [], [data]);
  const byId = useMemo(
    () => new Map(items.map((s) => [s.id, s])),
    [items],
  );

  // `draft` holds the optimistic order until the query refetches.
  const selectedIds = useMemo(() => {
    if (draft) return draft;
    return items
      .filter((s) => s.selected)
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
      .map((s) => s.id);
  }, [draft, items]);

  const selected = selectedIds
    .map((id) => byId.get(id))
    .filter((s): s is CatalogStyle => Boolean(s));

  const addable = items.filter(
    (s) =>
      !selectedIds.includes(s.id) &&
      s.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function commit(next: string[]) {
    setDraft(next);
    queueSelection(next);
  }

  function onDragEnd(event: DragEndEvent) {
    setDragId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = selectedIds.indexOf(String(active.id));
    const newIndex = selectedIds.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    commit(arrayMove(selectedIds, oldIndex, newIndex));
  }

  if (isLoading) return <Loader size="sm" />;

  const dragged = dragId ? byId.get(dragId) : undefined;

  return (
    <Stack gap="md">
      <div>
        <Title order={4}>{t('profile.styles.title')}</Title>
        <Text size="sm" c="dimmed">
          {t('profile.styles.description')}
        </Text>
      </div>

      {selected.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t('profile.styles.empty_hint')}
        </Text>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={(e: DragStartEvent) => setDragId(String(e.active.id))}
          onDragEnd={onDragEnd}
          onDragCancel={() => setDragId(null)}
        >
          <SortableContext items={selectedIds} strategy={verticalListSortingStrategy}>
            <Stack gap="xs">
              {selected.map((s) => (
                <SelectedStyleRow
                  key={s.id}
                  style={s}
                  onRemove={(id) => commit(selectedIds.filter((x) => x !== id))}
                />
              ))}
            </Stack>
          </SortableContext>
          <DragOverlay dropAnimation={null}>
            {dragged ? (
              <SelectedStyleRow style={dragged} onRemove={() => undefined} overlay />
            ) : null}
          </DragOverlay>
        </DndContext>
      )}

      <div>
        <Title order={5}>{t('profile.styles.add_title')}</Title>
        <TextInput
          mt="xs"
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          placeholder={t('profile.styles.add_placeholder')}
        />
        <Stack gap={4} mt="xs">
          {addable.map((s) => (
            <Group key={s.id} justify="space-between" wrap="nowrap">
              <Text size="sm">{s.name}</Text>
              <ActionIcon
                variant="subtle"
                aria-label={`add ${s.name}`}
                onClick={() => commit([...selectedIds, s.id])}
              >
                <IconPlus size={16} />
              </ActionIcon>
            </Group>
          ))}
        </Stack>
      </div>
    </Stack>
  );
}
```

- [ ] **Step 6: Mount it on the profile page**

Rewrite `frontend/src/routes/profile.tsx`:

```tsx
import { Button, Container, Divider, Group, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/useAuth';
import { IconLogout } from '../components/icons';
import { MyStylesSection } from '../features/profile/components/MyStylesSection';

export function ProfilePage() {
  const { t } = useTranslation();
  const { signOut, state } = useAuth();
  const name = state.status === 'authenticated' ? state.user.display_name : '';

  return (
    <Container size="sm" py="xl">
      <Stack gap="lg">
        <Group justify="space-between" align="center">
          <div>
            <Title order={2}>{t('appshell.profile')}</Title>
            <Text c="dimmed">{t('user_menu.signed_in_as', { name })}</Text>
          </div>
          <Button
            leftSection={<IconLogout size={16} />}
            variant="default"
            onClick={() => {
              void signOut();
            }}
          >
            {t('user_menu.sign_out')}
          </Button>
        </Group>

        <Divider />

        <MyStylesSection />
      </Stack>
    </Container>
  );
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && pnpm test -- MyStylesSection`
Expected: 4 passed. Also run any existing profile tests: `pnpm test -- profile`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/profile/ frontend/src/routes/profile.tsx frontend/src/i18n/en.json
git commit -m "feat(web): add my styles section to profile"
```

---

### Task 9: Admin screens keep the full catalog

**Files:**
- Modify: `frontend/src/features/admin/routes/AdminEnrichmentBacklogPage.tsx:22`, `frontend/src/features/admin/routes/AdminArtistEnrichmentBacklogPage.tsx:22`
- Test: `frontend/src/features/admin/routes/__tests__/AdminArtistEnrichmentBacklogPage.test.tsx` (update its hook mock)

**Interfaces:**
- Consumes: `useAllStyles` (Task 7). `CatalogStyle` carries `id` and `name`, which is all these pages read (`slugifyStyle(s.name)`).
- Produces: no new exports.

- [ ] **Step 1: Update the existing test's mock**

`frontend/src/features/admin/routes/__tests__/AdminArtistEnrichmentBacklogPage.test.tsx:54`
mocks the hook by module path. Once the page imports a different hook, that mock
silently stops applying and the test hits MSW instead. Change it:

```diff
-vi.mock('../../../../hooks/useStyles', () => ({
-  useStyles: () => ({ data: { items: [] }, isLoading: false }),
+vi.mock('../../../../hooks/useAllStyles', () => ({
+  useAllStyles: () => ({ data: { items: [] }, isLoading: false }),
 }));
```

Keep the rest of that file untouched. Leave the `useStyles` mocks in
`AddTracksModal.telemetry.test.tsx` and `ArtistsListPage.test.tsx` alone — those
pages stay personal on purpose.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- AdminArtistEnrichmentBacklogPage`
Expected: FAIL — the page still imports `useStyles`, so the `useAllStyles` mock
applies to nothing and the real hook runs without a handler.

- [ ] **Step 3: Switch both admin pages**

In each of `AdminEnrichmentBacklogPage.tsx` and `AdminArtistEnrichmentBacklogPage.tsx`:

```diff
-import { useStyles } from '../../../hooks/useStyles';
+import { useAllStyles } from '../../../hooks/useAllStyles';
```

```diff
-  const stylesQuery = useStyles();
+  const stylesQuery = useAllStyles();
```

Nothing else changes: both only read `s.name` off `stylesQuery.data?.items`, and
`CatalogStyle` carries `id` and `name`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm test -- Admin`
Expected: all admin tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/routes/
git commit -m "fix(web): keep admin backlog on the full catalog"
```

---

### Task 10: Browser test for reorder + full gate run

**Files:**
- Create: `frontend/src/features/profile/components/__tests__/MyStylesSection.browser.test.tsx`
- Test: the whole suite

**Interfaces:**
- Consumes: everything above.
- Produces: no new exports.

- [ ] **Step 1: Write the browser test**

Create `frontend/src/features/profile/components/__tests__/MyStylesSection.browser.test.tsx`:

```tsx
/**
 * Browser test — keyboard-driven dnd-kit reorder. jsdom applies no stylesheets
 * and no real layout, so the sortable list can only be verified here.
 */
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { MyStylesSection } from '../MyStylesSection';

const catalog = {
  items: [
    { id: 's1', name: 'Drum & Bass', selected: true, position: 0 },
    { id: 's2', name: 'House', selected: true, position: 1 },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

describe('MyStylesSection (browser)', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/styles', () => HttpResponse.json(catalog)),
    );
  });

  it('keyboard reorder sends the swapped order', async () => {
    let body: { style_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/me/styles', async ({ request }) => {
        body = (await request.json()) as { style_ids: string[] };
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <MyStylesSection />
        </MantineProvider>
      </QueryClientProvider>,
    );

    await screen.findByText('Drum & Bass');
    const handles = screen.getAllByRole('button', { name: /Reorder/i });

    handles[0].focus();
    await userEvent.keyboard('{ }');          // pick up
    await userEvent.keyboard('{ArrowDown}');  // move below "House"
    await userEvent.keyboard('{ }');          // drop

    await waitFor(() => expect(body).toEqual({ style_ids: ['s2', 's1'] }));
  });
});
```

- [ ] **Step 2: Run the browser test**

Run: `cd frontend && pnpm test:browser -- MyStylesSection`
Expected: PASS. If the keyboard sensor needs a different key (`{Space}` vs `{ }`) in this Playwright version, adjust the key, not the component.

- [ ] **Step 3: Run every gate**

Run:
```bash
pytest -q
cd frontend && pnpm typecheck && pnpm lint && pnpm test
```
Expected: all green. Report any failure with its output rather than adjusting the test to match broken behaviour.

- [ ] **Step 4: Verify the generated contract is in sync**

Run:
```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
git diff --exit-code docs/api/openapi.yaml frontend/src/api/schema.d.ts
```
Expected: no diff (Task 6 already committed the regenerated files).

- [ ] **Step 5: Refresh the knowledge graph**

Run: `graphify . --update`
This re-extracts only changed files; skipping it leaves the new `user_styles` package invisible to graph queries.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/profile/components/__tests__/MyStylesSection.browser.test.tsx graphify-out/
git commit -m "test(web): cover style reorder in a real browser"
```

---

## Deployment (manual, after review)

Not part of the task list — run in this order once the branch is merged:

1. `alembic upgrade head` (creates the table; safe — an empty table means current behaviour).
2. `scripts/package_lambda.sh` + deploy the collector Lambda.
3. `cd infra && terraform apply` (adds `PUT /me/styles`).
4. Deploy the frontend.

Steps 1–3 are backward compatible; the frontend must go last because it is the only caller of the new route.
