# User Label Preferences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-user like/dislike state on labels, surfaced in the navbar, library list (with filter), label detail header, and the curate player tile (which now always shows the label name when a track has a `label_id`).

**Architecture:** Single new overlay table `clouder_user_label_prefs(user_id, label_id, status)` mirrors the tenancy pattern. Backend adds `PUT /labels/{id}/preference`, `GET /me/label-preferences`, plus projects `my_preference` into `GET /labels` and `GET /labels/{id}`. Frontend adds a shared `LabelPreferenceButtons` component fed by a `useSetLabelPreference` mutation with optimistic cache patching. `LabelTile`'s contract changes: it returns `null` only when there is no `labelId` (used to return `null` when info was missing).

**Tech Stack:** Aurora PostgreSQL via RDS Data API, AWS Lambda, API Gateway v2 (Terraform), Pydantic, pytest. Frontend: React 19, Mantine 9, TanStack Query 5, react-i18next, openapi-typescript, vitest.

**Spec:** `docs/superpowers/specs/2026-05-19-user-label-preferences-design.md` (commit `f15437a`).

**Branch:** start on `docs/user-label-preferences-spec`; rename to `feat/user-label-preferences` in Task 0.1. All commits stay on that branch.

**Hard policy (enforced by pre-commit hooks):**
- Conventional Commits, scope-prefixed (`feat(backend):`, `feat(frontend):`, `feat(infra):`, `docs(spec):`, `test(...):`, etc.).
- Multi-line commit bodies use heredoc form: `git commit -m "$(cat <<'EOF' ... EOF)"`.
- NO `Co-Authored-By:` trailer — caveman-commit hook strips/blocks it.
- Never run `git push` or merge to main during execution.

---

## File map

### Backend

| File                                                                                  | Status    | Responsibility                                                  |
|---------------------------------------------------------------------------------------|-----------|-----------------------------------------------------------------|
| `alembic/versions/20260519_23_user_label_prefs.py`                                    | NEW       | Migration: create `clouder_user_label_prefs` + index            |
| `src/collector/label_enrichment/repository.py`                                        | MODIFIED  | Add prefs CRUD; project `my_preference` in label queries        |
| `src/collector/label_enrichment/routes.py`                                            | MODIFIED  | Add `handle_put_label_preference`, `handle_get_my_label_preferences`; forward `user_id` + `my` to repo |
| `src/collector/handler.py`                                                            | MODIFIED  | Register `PUT /labels/{label_id}/preference` and `GET /me/label-preferences` |
| `infra/api_gateway.tf`                                                                | MODIFIED  | Two new `aws_apigatewayv2_route` resources                      |
| `scripts/generate_openapi.py`                                                         | MODIFIED  | Extend `LabelSummary`, `LabelDetail`, add `my` param to `/labels`, add 2 new routes |
| `tests/unit/test_handler_label_preference.py`                                         | NEW       | Unit tests for the new handlers                                 |
| `tests/unit/test_label_enrichment_prefs_repo.py`                                      | NEW       | Unit tests for prefs repository methods                         |
| `tests/integration/test_user_label_prefs_e2e.py`                                      | NEW       | End-to-end: PUT → GET projects `my_preference` correctly        |
| `docs/api/openapi.yaml`                                                               | REGEN     | Output of `scripts/generate_openapi.py`                         |

### Frontend

| File                                                                                  | Status    | Responsibility                                                  |
|---------------------------------------------------------------------------------------|-----------|-----------------------------------------------------------------|
| `frontend/src/api/schema.d.ts`                                                        | REGEN     | Generated from `docs/api/openapi.yaml` via `pnpm api:types`     |
| `frontend/src/api/labels.ts`                                                          | UNCHANGED | Re-exports use the regenerated types automatically              |
| `frontend/src/components/icons.ts`                                                    | MODIFIED  | Re-export `IconBook`, `IconHeart`, `IconHeartFilled`            |
| `frontend/src/i18n/en.json`                                                           | MODIFIED  | New keys: `appshell.library`, `library.prefs.*`, filter labels  |
| `frontend/src/routes/_layout.tsx`                                                     | MODIFIED  | Add Library nav item between Playlists and Profile              |
| `frontend/src/features/library/hooks/useSetLabelPreference.ts`                        | NEW       | `useMutation` hook with optimistic cache patching               |
| `frontend/src/features/library/hooks/useLabelsList.ts`                                | MODIFIED  | Pass `my` filter param to API + include in queryKey             |
| `frontend/src/features/library/components/LabelPreferenceButtons.tsx`                 | NEW       | Heart + cross icons; shared by tile/table/detail                |
| `frontend/src/features/library/components/LabelTile.tsx`                              | MODIFIED  | New `labelName` prop; always render when `labelId` present      |
| `frontend/src/features/library/components/LabelsTable.tsx`                            | MODIFIED  | New `My` column                                                  |
| `frontend/src/features/library/components/LibraryFilters.tsx`                         | MODIFIED  | New `my` SegmentedControl                                       |
| `frontend/src/features/library/components/LabelDetailHeader.tsx`                      | MODIFIED  | Buttons next to AI badge                                        |
| `frontend/src/features/library/routes/LibraryListPage.tsx`                            | MODIFIED  | Wire `my` URL param                                              |
| `frontend/src/features/curate/components/CurateSession.tsx`                           | MODIFIED  | Pass `labelName` to `<LabelTile />`                              |
| `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`                 | MODIFIED  | Pass `labelName` to `<LabelTile />`                              |
| `frontend/src/features/library/hooks/__tests__/useSetLabelPreference.test.tsx`        | NEW       | Optimistic update + rollback                                    |
| `frontend/src/features/library/components/__tests__/LabelPreferenceButtons.test.tsx`  | NEW       | Click behaviour                                                  |
| `frontend/src/features/library/components/__tests__/LabelTile.test.tsx`               | MODIFIED  | New no-info case                                                 |
| `frontend/src/features/library/components/__tests__/LabelsTable.test.tsx`             | NEW       | `My` column renders                                              |

---

## Phase 0 — branch rename

### Task 0.1: Rename the branch

**Files:** none — git plumbing only.

- [ ] **Step 1: Confirm current branch and rename**

```bash
git rev-parse --abbrev-ref HEAD
# expected: docs/user-label-preferences-spec

git branch -m feat/user-label-preferences
git rev-parse --abbrev-ref HEAD
# expected: feat/user-label-preferences
```

No commit needed — branch rename does not create a commit. All subsequent commits land on `feat/user-label-preferences`.

---

## Phase 1 — Backend

**Sequential.** Tasks 1.1 → 1.7 touch overlapping files (`repository.py`, `routes.py`); keep them in order. Do not run Phase 2 until 1.7 finishes.

### Task 1.1: Alembic migration for `clouder_user_label_prefs`

**Files:**
- Create: `alembic/versions/20260519_23_user_label_prefs.py`

The codebase uses `String(36)` everywhere for surrogate keys (see `users.id`, `clouder_labels.id` in `20260301_01_init_clouder_schema.py`). Use the same here — do **not** introduce `UUID`/`uuid_generate_v4`.

- [ ] **Step 1: Write the migration**

```python
"""user label preferences

Revision ID: 20260519_23
Revises: 20260518_22
Create Date: 2026-05-19 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260519_23"
down_revision = "20260518_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clouder_user_label_prefs",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("label_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "label_id", name="pk_user_label_prefs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_user_label_prefs_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["label_id"], ["clouder_labels.id"],
            name="fk_user_label_prefs_label",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('liked', 'disliked')",
            name="ck_user_label_prefs_status",
        ),
    )
    op.create_index(
        "idx_user_label_prefs_user_status",
        "clouder_user_label_prefs",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_label_prefs_user_status",
        table_name="clouder_user_label_prefs",
    )
    op.drop_table("clouder_user_label_prefs")
```

- [ ] **Step 2: Run the migration locally**

```bash
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
```

Expected: `Running upgrade 20260518_22 -> 20260519_23, user label preferences`. Then `alembic downgrade -1` to confirm rollback, then `alembic upgrade head` again to re-apply.

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/20260519_23_user_label_prefs.py
git commit -m "feat(backend): add clouder_user_label_prefs table"
```

---

### Task 1.2: Repository — `upsert_user_label_pref` / `delete_user_label_pref`

**Files:**
- Modify: `src/collector/label_enrichment/repository.py` (append two methods to `LabelEnrichmentRepository`)
- Test: `tests/unit/test_label_enrichment_prefs_repo.py` (new)

- [ ] **Step 1: Write the failing test**

`tests/unit/test_label_enrichment_prefs_repo.py`:

```python
"""LabelEnrichmentRepository: user label preference CRUD."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from collector.label_enrichment.repository import LabelEnrichmentRepository


class FakeDataApi:
    """Minimal stub: records (sql, params) per call, returns scripted rows."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.scripted: list[list[dict[str, Any]]] = []

    def script(self, *batches: list[dict[str, Any]]) -> None:
        self.scripted.extend(batches)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.calls.append((sql, dict(params or {})))
        if self.scripted:
            return self.scripted.pop(0)
        return []


def _fixed_now() -> datetime:
    return datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


def test_upsert_user_label_pref_emits_upsert_sql():
    api = FakeDataApi()
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.upsert_user_label_pref(user_id="u-1", label_id="lbl-1", status="liked")

    assert len(api.calls) == 1
    sql, params = api.calls[0]
    assert "INSERT INTO clouder_user_label_prefs" in sql
    assert "ON CONFLICT" in sql
    assert params == {
        "user_id": "u-1",
        "label_id": "lbl-1",
        "status": "liked",
        "ts": _fixed_now(),
    }


def test_upsert_rejects_unknown_status():
    api = FakeDataApi()
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)
    with pytest.raises(ValueError):
        repo.upsert_user_label_pref(user_id="u-1", label_id="lbl-1", status="loved")


def test_delete_user_label_pref_emits_delete_sql():
    api = FakeDataApi()
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.delete_user_label_pref(user_id="u-1", label_id="lbl-1")

    sql, params = api.calls[0]
    assert sql.strip().startswith("DELETE FROM clouder_user_label_prefs")
    assert params == {"user_id": "u-1", "label_id": "lbl-1"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
export PYTHONPATH=src
pytest tests/unit/test_label_enrichment_prefs_repo.py -v
```

Expected: FAIL with `AttributeError: 'LabelEnrichmentRepository' object has no attribute 'upsert_user_label_pref'`.

- [ ] **Step 3: Implement the methods**

Append to `src/collector/label_enrichment/repository.py` inside `class LabelEnrichmentRepository`, after `get_label_info_for_user`:

```python
    # ── user label preferences ──────────────────────────────────────
    def upsert_user_label_pref(
        self,
        *,
        user_id: str,
        label_id: str,
        status: str,
    ) -> None:
        if status not in ("liked", "disliked"):
            raise ValueError(f"status must be 'liked' or 'disliked', got {status!r}")
        self._data_api.execute(
            """
            INSERT INTO clouder_user_label_prefs (user_id, label_id, status, updated_at)
            VALUES (:user_id, :label_id, :status, :ts)
            ON CONFLICT (user_id, label_id) DO UPDATE
            SET status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "user_id": user_id,
                "label_id": label_id,
                "status": status,
                "ts": self._now(),
            },
        )

    def delete_user_label_pref(self, *, user_id: str, label_id: str) -> None:
        self._data_api.execute(
            "DELETE FROM clouder_user_label_prefs WHERE user_id = :user_id AND label_id = :label_id",
            {"user_id": user_id, "label_id": label_id},
        )
```

- [ ] **Step 4: Verify the test passes**

```bash
pytest tests/unit/test_label_enrichment_prefs_repo.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_prefs_repo.py
git commit -m "feat(backend): upsert/delete user label preference"
```

---

### Task 1.3: Repository — `list_user_label_prefs`

**Files:**
- Modify: `src/collector/label_enrichment/repository.py`
- Test: `tests/unit/test_label_enrichment_prefs_repo.py` (append)

- [ ] **Step 1: Append the failing test**

Append to `tests/unit/test_label_enrichment_prefs_repo.py`:

```python
def test_list_user_label_prefs_paginates_and_filters_by_status():
    api = FakeDataApi()
    api.script(
        [
            {"id": "lbl-1", "name": "Fokuz", "status": "liked"},
            {"id": "lbl-2", "name": "Drumcode", "status": "liked"},
        ],
        [{"c": 7}],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    items, total = repo.list_user_label_prefs(
        user_id="u-1", status="liked", page=2, limit=2,
    )

    assert total == 7
    assert [it["id"] for it in items] == ["lbl-1", "lbl-2"]
    assert all(it["my_preference"] == "liked" for it in items)

    sql, params = api.calls[0]
    assert "FROM clouder_user_label_prefs p" in sql
    assert "JOIN clouder_labels lbl" in sql
    assert "p.status = :status" in sql
    assert params == {
        "user_id": "u-1",
        "status": "liked",
        "lim": 2,
        "off": 2,  # (page-1)*limit = (2-1)*2
    }
```

- [ ] **Step 2: Verify the test fails**

```bash
pytest tests/unit/test_label_enrichment_prefs_repo.py::test_list_user_label_prefs_paginates_and_filters_by_status -v
```

Expected: FAIL with `AttributeError: ... has no attribute 'list_user_label_prefs'`.

- [ ] **Step 3: Implement the method**

Append to `LabelEnrichmentRepository`:

```python
    def list_user_label_prefs(
        self,
        *,
        user_id: str,
        status: str,
        page: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if status not in ("liked", "disliked"):
            raise ValueError(f"status must be 'liked' or 'disliked', got {status!r}")
        offset = max(page - 1, 0) * limit
        rows = self._data_api.execute(
            """
            SELECT lbl.id, lbl.name, p.status
            FROM clouder_user_label_prefs p
            JOIN clouder_labels lbl ON lbl.id = p.label_id
            WHERE p.user_id = :user_id AND p.status = :status
            ORDER BY p.updated_at DESC, lbl.id DESC
            LIMIT :lim OFFSET :off
            """,
            {"user_id": user_id, "status": status, "lim": limit, "off": offset},
        )
        items = [
            {"id": r["id"], "name": r["name"], "my_preference": r["status"]}
            for r in rows
        ]
        total_rows = self._data_api.execute(
            """
            SELECT COUNT(*) AS c
            FROM clouder_user_label_prefs p
            WHERE p.user_id = :user_id AND p.status = :status
            """,
            {"user_id": user_id, "status": status},
        )
        total = int(total_rows[0]["c"]) if total_rows else 0
        return items, total
```

- [ ] **Step 4: Verify the test passes**

```bash
pytest tests/unit/test_label_enrichment_prefs_repo.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_prefs_repo.py
git commit -m "feat(backend): list user label preferences"
```

---

### Task 1.4: Repository — project `my_preference` in `list_labels` and apply `my` filter

**Files:**
- Modify: `src/collector/label_enrichment/repository.py` — function `list_labels`
- Test: `tests/unit/test_label_enrichment_prefs_repo.py` (append)

The `list_labels` signature gains `user_id: str | None` and `my: str` (`"all"|"liked"|"disliked"|"unrated"`). When `user_id is None` (defensive — should never happen in practice since the route is authenticated), `my_preference` is always `None` and `my` is ignored.

- [ ] **Step 1: Append the failing test**

Append to `tests/unit/test_label_enrichment_prefs_repo.py`:

```python
def test_list_labels_projects_my_preference_via_left_join():
    api = FakeDataApi()
    api.script(
        [
            {
                "id": "lbl-1", "name": "Fokuz", "dominant_style": "drum-and-bass",
                "track_count": 3, "status": "completed",
                "tagline": "t", "country": "NL", "founded_year": 2007,
                "primary_styles": ["liquid"], "activity": "steady",
                "ai_content": "none_detected", "updated_at": _fixed_now(),
                "my_preference": "liked",
            },
        ],
        [{"c": 1}],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    items, total = repo.list_labels(
        style=None, q=None, sort="name", page=1, limit=50,
        user_id="u-1", my="all",
    )

    assert total == 1
    assert items[0]["my_preference"] == "liked"

    main_sql, _ = api.calls[0]
    assert "LEFT JOIN clouder_user_label_prefs ulp" in main_sql
    assert "ulp.user_id = :pref_user_id" in main_sql
    assert "ulp.status AS my_preference" in main_sql


def test_list_labels_my_liked_uses_inner_filter():
    api = FakeDataApi()
    api.script([], [{"c": 0}])
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.list_labels(
        style=None, q=None, sort="name", page=1, limit=50,
        user_id="u-1", my="liked",
    )

    main_sql, params = api.calls[0]
    assert "ulp.status = 'liked'" in main_sql
    assert params["pref_user_id"] == "u-1"


def test_list_labels_my_unrated_uses_anti_join():
    api = FakeDataApi()
    api.script([], [{"c": 0}])
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    repo.list_labels(
        style=None, q=None, sort="name", page=1, limit=50,
        user_id="u-1", my="unrated",
    )

    main_sql, _ = api.calls[0]
    assert "ulp.user_id IS NULL" in main_sql
```

- [ ] **Step 2: Verify the tests fail**

```bash
pytest tests/unit/test_label_enrichment_prefs_repo.py -v
```

Expected: 3 new tests FAIL with `TypeError: list_labels() got an unexpected keyword argument 'user_id'`.

- [ ] **Step 3: Update `list_labels`**

Replace the existing `list_labels` body (currently lines ~93–208 in `src/collector/label_enrichment/repository.py`) with the version below. Changes vs. existing: new `user_id`/`my` kwargs, LEFT JOIN to `clouder_user_label_prefs`, projection of `my_preference`, optional filter clauses, and `my_preference` field on each item.

```python
    def list_labels(
        self,
        *,
        style: str | None,
        q: str | None,
        sort: str,
        page: int,
        limit: int,
        user_id: str | None = None,
        my: str = "all",
    ) -> tuple[list[dict[str, Any]], int]:
        """User-facing label list with page-based pagination.

        Includes a LEFT JOIN to `clouder_user_label_prefs` for the current user
        so each item carries `my_preference`. When `my` is `"liked"` /
        `"disliked"` / `"unrated"`, the join is narrowed accordingly. When
        `user_id` is None the join contributes no rows; `my_preference` is
        always None.
        """
        if my not in ("all", "liked", "disliked", "unrated"):
            raise ValueError(f"my must be one of all|liked|disliked|unrated, got {my!r}")

        where: list[str] = []
        params: dict[str, Any] = {"lim": limit, "off": max(page - 1, 0) * limit}
        if style:
            where.append(
                "EXISTS (SELECT 1 FROM label_style_counts lsc "
                "WHERE lsc.label_id = lbl.id AND lsc.style_slug = LOWER(:style))"
            )
            params["style"] = style
        if q:
            where.append("LOWER(lbl.name) LIKE :q")
            params["q"] = f"{q.lower()}%"

        # `pref_user_id` is bound even when user_id is None so the LEFT JOIN's
        # `ulp.user_id = :pref_user_id` predicate never matches — equivalent
        # to leaving `my_preference` always-null.
        params["pref_user_id"] = user_id or ""

        if my == "liked":
            where.append("ulp.status = 'liked'")
        elif my == "disliked":
            where.append("ulp.status = 'disliked'")
        elif my == "unrated":
            where.append("ulp.user_id IS NULL")

        order_by = (
            "li.updated_at DESC NULLS LAST, lbl.id DESC"
            if sort == "recent"
            else "lbl.name ASC, lbl.id ASC"
        )
        where_sql = " AND ".join(where) if where else "TRUE"

        ctes = f"""
            WITH label_track_counts AS (
                SELECT a.label_id, COUNT(*) AS cnt
                FROM clouder_albums a
                JOIN clouder_tracks t ON t.album_id = a.id
                WHERE a.label_id IS NOT NULL
                GROUP BY a.label_id
            ),
            label_style_counts AS (
                SELECT
                    a.label_id,
                    {_STYLE_SLUG_EXPR} AS style_slug,
                    COUNT(*) AS cnt
                FROM clouder_albums a
                JOIN clouder_tracks t ON t.album_id = a.id
                JOIN clouder_styles s ON s.id = t.style_id
                WHERE a.label_id IS NOT NULL
                GROUP BY a.label_id, s.name
            ),
            label_dominant_style AS (
                SELECT DISTINCT ON (label_id) label_id, style_slug
                FROM label_style_counts
                ORDER BY label_id, cnt DESC
            )
        """

        rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT lbl.id, lbl.name,
                   CASE WHEN li.label_id IS NULL THEN 'none' ELSE 'completed' END AS status,
                   li.tagline, li.country, li.founded_year, li.primary_styles,
                   li.activity, li.ai_content, li.updated_at,
                   lds.style_slug AS dominant_style,
                   COALESCE(ltc.cnt, 0) AS track_count,
                   ulp.status AS my_preference
            FROM clouder_labels lbl
            LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
            LEFT JOIN label_dominant_style lds ON lds.label_id = lbl.id
            LEFT JOIN label_track_counts ltc ON ltc.label_id = lbl.id
            LEFT JOIN clouder_user_label_prefs ulp
                ON ulp.label_id = lbl.id AND ulp.user_id = :pref_user_id
            WHERE {where_sql}
            ORDER BY {order_by}
            LIMIT :lim OFFSET :off
            """,
            params,
        )

        items: list[dict[str, Any]] = []
        for r in rows:
            info = None
            if r.get("status") == "completed":
                primary = r.get("primary_styles") or []
                info = {
                    "tagline": r.get("tagline"),
                    "country": r.get("country"),
                    "founded_year": r.get("founded_year"),
                    "primary_styles": primary,
                    "activity": r.get("activity") or "unknown",
                    "ai_content": r.get("ai_content"),
                    "updated_at": r.get("updated_at"),
                }
            items.append({
                "id": r["id"],
                "name": r["name"],
                "style": r.get("dominant_style") or "",
                "status": r.get("status") or "none",
                "track_count": int(r.get("track_count") or 0),
                "info": info,
                "my_preference": r.get("my_preference"),
            })

        count_params = {k: v for k, v in params.items() if k not in ("lim", "off")}
        total_rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT COUNT(*) AS c
            FROM clouder_labels lbl
            LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
            LEFT JOIN clouder_user_label_prefs ulp
                ON ulp.label_id = lbl.id AND ulp.user_id = :pref_user_id
            WHERE {where_sql}
            """,
            count_params,
        )
        total = int(total_rows[0]["c"]) if total_rows else 0
        return items, total
```

- [ ] **Step 4: Verify all repo tests pass**

```bash
pytest tests/unit/test_label_enrichment_prefs_repo.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Verify existing `list_labels` callers still work**

```bash
pytest tests/unit -v -k "labels_list or labels_detail"
```

Expected: every previously-passing test still passes (`list_labels` accepts the new kwargs as optional). If any test fails because it calls `list_labels` with positional args or asserts on the row dict missing `my_preference`, update the test to pass `user_id=None, my="all"` and tolerate the new key.

- [ ] **Step 6: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_prefs_repo.py
git commit -m "feat(backend): project my_preference in list_labels"
```

---

### Task 1.5: Repository — project `my_preference` in `get_label_info_for_user`

**Files:**
- Modify: `src/collector/label_enrichment/repository.py` — function `get_label_info_for_user`
- Test: `tests/unit/test_label_enrichment_prefs_repo.py` (append)

Signature change: `get_label_info_for_user(label_id, user_id=None)`. The function must return a dict (with `my_preference: "liked"|"disliked"|None`) whenever a `clouder_label_info` row OR a `clouder_user_label_prefs` row exists. Spec section 3.7 requires preference buttons to work on the detail page even before the label is enriched — so we now return a minimal payload (`label_name`, `my_preference`) when info is missing but the label exists.

- [ ] **Step 1: Append the failing test**

```python
def test_get_label_info_for_user_includes_my_preference_when_info_present():
    api = FakeDataApi()
    api.script(
        [{
            "merged": {
                "label_name": "Fokuz",
                "country": "NL",
                "summary": "Rotterdam liquid label.",
                "ai_content": "none_detected",
            },
            "my_preference": "liked",
        }],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    out = repo.get_label_info_for_user("lbl-1", user_id="u-1")

    assert out is not None
    assert out["label_name"] == "Fokuz"
    assert out["my_preference"] == "liked"


def test_get_label_info_for_user_returns_minimal_payload_when_info_missing():
    api = FakeDataApi()
    # First call (merged JSONB) — no info row.
    # Second call (fallback) — label exists; pref returned as None.
    api.script(
        [],
        [{"label_name": "Drumcode", "my_preference": None}],
    )
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)

    out = repo.get_label_info_for_user("lbl-2", user_id="u-1")

    assert out == {"label_name": "Drumcode", "my_preference": None}


def test_get_label_info_for_user_returns_none_when_label_missing():
    api = FakeDataApi()
    api.script([], [])  # info miss, label miss
    repo = LabelEnrichmentRepository(data_api=api, now=_fixed_now)
    assert repo.get_label_info_for_user("nope", user_id="u-1") is None
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tests/unit/test_label_enrichment_prefs_repo.py -v
```

Expected: the three new tests fail (`my_preference` missing, or function still returns None when info missing).

- [ ] **Step 3: Replace `get_label_info_for_user`**

Replace the existing body in `src/collector/label_enrichment/repository.py`:

```python
    def get_label_info_for_user(
        self,
        label_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return decoded merged LabelInfo for a user-facing detail page.

        When `clouder_label_info` has a row, returns the decoded `merged`
        JSONB blob with admin-only fields stripped, plus `my_preference`.
        When the row is missing but the label exists, returns a minimal
        `{label_name, my_preference}` payload so preference buttons can
        still render on the detail page. Returns None only when the label
        itself does not exist.
        """
        rows = self._data_api.execute(
            """
            SELECT li.merged, ulp.status AS my_preference
            FROM clouder_label_info li
            LEFT JOIN clouder_user_label_prefs ulp
                ON ulp.label_id = li.label_id AND ulp.user_id = :user_id
            WHERE li.label_id = :id
            LIMIT 1
            """,
            {"id": label_id, "user_id": user_id or ""},
        )
        if rows:
            merged = rows[0].get("merged")
            if isinstance(merged, str):
                merged = json.loads(merged)
            if not isinstance(merged, dict):
                return None
            out = {k: v for k, v in merged.items() if k not in _USER_FACING_FORBIDDEN}
            out["my_preference"] = rows[0].get("my_preference")
            return out

        fallback = self._data_api.execute(
            """
            SELECT lbl.name AS label_name, ulp.status AS my_preference
            FROM clouder_labels lbl
            LEFT JOIN clouder_user_label_prefs ulp
                ON ulp.label_id = lbl.id AND ulp.user_id = :user_id
            WHERE lbl.id = :id
            LIMIT 1
            """,
            {"id": label_id, "user_id": user_id or ""},
        )
        if not fallback:
            return None
        row = fallback[0]
        return {
            "label_name": row.get("label_name"),
            "my_preference": row.get("my_preference"),
        }
```

- [ ] **Step 4: Verify all repo tests pass**

```bash
pytest tests/unit/test_label_enrichment_prefs_repo.py tests/unit/test_handler_labels_detail.py -v
```

Expected: all green. If `test_handler_labels_detail.py::test_get_label_user_returns_404_when_not_completed` now fails because the handler returns 200 with a minimal payload, that's the intended contract change — update the test in Step 5.

- [ ] **Step 5: Update the existing 404 test in `tests/unit/test_handler_labels_detail.py`**

The previously 404-returning case (no `clouder_label_info` row) now returns 200 with `{label_name, my_preference: null}`. Modify the test:

```python
def test_get_label_user_returns_minimal_payload_when_not_completed(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = {
        "label_name": "Drumcode",
        "my_preference": None,
    }
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_user_event("lbl-x"), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body == {"label_name": "Drumcode", "my_preference": None}


def test_get_label_user_returns_404_when_label_missing(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = None
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_user_event("nope"), None)
    assert resp["statusCode"] == 404
```

Run: `pytest tests/unit/test_handler_labels_detail.py -v`. Expected: 3 passed (the unchanged `test_get_label_user_returns_sanitized_payload`, plus the two updated tests).

- [ ] **Step 6: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_prefs_repo.py tests/unit/test_handler_labels_detail.py
git commit -m "feat(backend): project my_preference in label detail"
```

---

### Task 1.6: Routes — PUT/GET handlers + forward `user_id` and `my` to existing handlers

**Files:**
- Modify: `src/collector/label_enrichment/routes.py`
- Test: `tests/unit/test_handler_label_preference.py` (new)

The `_extract_user_id` helper already exists at the top of `routes.py`. Reuse it.

- [ ] **Step 1: Write the failing handler test**

`tests/unit/test_handler_label_preference.py`:

```python
"""PUT /labels/{id}/preference + GET /me/label-preferences."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


def _user_event(route: str, *, body: dict | None = None,
                path: dict | None = None, qs: dict | None = None) -> dict:
    return {
        "routeKey": route,
        "pathParameters": path or {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


def test_put_pref_liked_calls_upsert(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": "liked"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204
    fake_repo.upsert_user_label_pref.assert_called_once_with(
        user_id="u-1", label_id="lbl-1", status="liked",
    )
    fake_repo.delete_user_label_pref.assert_not_called()


def test_put_pref_none_calls_delete(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": "none"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204
    fake_repo.delete_user_label_pref.assert_called_once_with(
        user_id="u-1", label_id="lbl-1",
    )
    fake_repo.upsert_user_label_pref.assert_not_called()


def test_put_pref_404_when_label_missing(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = None
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": "liked"},
            path={"label_id": "nope"},
        ),
        None,
    )
    assert resp["statusCode"] == 404


@pytest.mark.parametrize("bad", ["loved", "", None, 7])
def test_put_pref_422_on_invalid_status(monkeypatch, bad):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "PUT /labels/{label_id}/preference",
            body={"status": bad},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 400  # ValidationError → 400 in this codebase


def test_get_my_label_preferences_passes_user_id(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_user_label_prefs.return_value = (
        [{"id": "lbl-1", "name": "Fokuz", "my_preference": "liked"}],
        1,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(
        _user_event(
            "GET /me/label-preferences",
            qs={"status": "liked", "page": "1", "limit": "50"},
        ),
        None,
    )
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body == {
        "items": [{"id": "lbl-1", "name": "Fokuz", "my_preference": "liked"}],
        "total": 1, "page": 1, "limit": 50,
    }
    fake_repo.list_user_label_prefs.assert_called_once_with(
        user_id="u-1", status="liked", page=1, limit=50,
    )


def test_labels_list_forwards_my_and_user_id(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_labels.return_value = ([], 0)
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    handler.lambda_handler(
        _user_event(
            "GET /labels",
            qs={"my": "liked", "page": "1", "limit": "50", "sort": "name"},
        ),
        None,
    )
    kwargs = fake_repo.list_labels.call_args.kwargs
    assert kwargs["my"] == "liked"
    assert kwargs["user_id"] == "u-1"


def test_label_detail_forwards_user_id(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = {
        "label_name": "Fokuz", "my_preference": "liked",
    }
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    handler.lambda_handler(
        _user_event(
            "GET /labels/{label_id}",
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    fake_repo.get_label_info_for_user.assert_called_once_with(
        "lbl-1", user_id="u-1",
    )
```

- [ ] **Step 2: Verify the tests fail**

```bash
pytest tests/unit/test_handler_label_preference.py -v
```

Expected: every test fails (`Route not found` for new routes, missing kwargs for existing ones).

- [ ] **Step 3: Add new handlers and update existing ones**

Append to `src/collector/label_enrichment/routes.py`:

```python
def handle_put_label_preference(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    user_id = _extract_user_id(event)
    if not user_id:
        raise ValidationError("user_id is required")

    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")
    status = body.get("status")
    if status not in ("liked", "disliked", "none"):
        raise ValidationError("status must be one of: liked, disliked, none")

    repo = _build_repository()
    if repo.get_label_by_id(label_id) is None:
        return 404, {"error_code": "label_not_found", "message": "label not found"}

    if status == "none":
        repo.delete_user_label_pref(user_id=user_id, label_id=label_id)
    else:
        repo.upsert_user_label_pref(
            user_id=user_id, label_id=label_id, status=status,
        )
    return 204, {}


def handle_get_my_label_preferences(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    status = (qs.get("status") or "liked").strip()
    if status not in ("liked", "disliked"):
        raise ValidationError("status must be 'liked' or 'disliked'")
    try:
        page = int(qs.get("page") or "1")
    except (TypeError, ValueError):
        raise ValidationError("page must be an integer")
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if page < 1:
        raise ValidationError("page must be >= 1")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    user_id = _extract_user_id(event)
    if not user_id:
        raise ValidationError("user_id is required")
    repo = _build_repository()
    items, total = repo.list_user_label_prefs(
        user_id=user_id, status=status, page=page, limit=limit,
    )
    return 200, {"items": items, "total": total, "page": page, "limit": limit}
```

Then replace the bodies of `handle_get_labels_list` and `handle_get_label_user` to forward `user_id` / `my`:

```python
def handle_get_labels_list(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    style = (qs.get("style") or "").strip() or None
    q = (qs.get("q") or "").strip() or None
    sort = (qs.get("sort") or "name").strip()
    if sort not in ("name", "recent"):
        raise ValidationError("sort must be 'name' or 'recent'")
    my = (qs.get("my") or "all").strip()
    if my not in ("all", "liked", "disliked", "unrated"):
        raise ValidationError("my must be one of: all, liked, disliked, unrated")
    try:
        page = int(qs.get("page") or "1")
    except (TypeError, ValueError):
        raise ValidationError("page must be an integer")
    if page < 1:
        raise ValidationError("page must be >= 1")
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    repo = _build_repository()
    user_id = _extract_user_id(event)
    items, total = repo.list_labels(
        style=style, q=q, sort=sort, page=page, limit=limit,
        user_id=user_id, my=my,
    )
    return 200, {"items": items, "total": total, "page": page, "limit": limit}


def handle_get_label_user(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    repo = _build_repository()
    user_id = _extract_user_id(event)
    row = repo.get_label_info_for_user(label_id, user_id=user_id)
    if row is None:
        return 404, {"error_code": "label_not_found", "message": "label not found"}
    return 200, row
```

- [ ] **Step 4: Register the two new routes in `src/collector/handler.py`**

In `_route`, add (before the existing `if route_key == "GET /labels":` clause):

```python
    if route_key == "PUT /labels/{label_id}/preference":
        from .label_enrichment.routes import handle_put_label_preference
        status, body = handle_put_label_preference(event)
        if status == 204:
            return {
                "statusCode": 204,
                "headers": {"x-correlation-id": correlation_id},
                "body": "",
            }
        return _json_response(status, body, correlation_id)
    if route_key == "GET /me/label-preferences":
        from .label_enrichment.routes import handle_get_my_label_preferences
        status, body = handle_get_my_label_preferences(event)
        return _json_response(status, body, correlation_id)
```

- [ ] **Step 5: Verify the handler tests pass**

```bash
pytest tests/unit/test_handler_label_preference.py -v
pytest tests/unit/test_handler_labels_backlog.py tests/unit/test_handler_labels_detail.py -v
```

Expected: all green. If existing handler tests fail because `handle_get_labels_list` previously took no `my` argument, they should be unaffected since `my` defaults to `"all"`.

- [ ] **Step 6: Commit**

```bash
git add src/collector/label_enrichment/routes.py src/collector/handler.py tests/unit/test_handler_label_preference.py
git commit -m "feat(backend): label preference endpoints + my filter forwarding"
```

---

### Task 1.7: Terraform — register two new API Gateway routes

**Files:**
- Modify: `infra/api_gateway.tf`

- [ ] **Step 1: Append two new resources at the end of the existing routes block**

After `resource "aws_apigatewayv2_route" "label_history"` (currently around line 169):

```hcl
resource "aws_apigatewayv2_route" "label_preference_put" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "PUT /labels/{label_id}/preference"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "my_label_preferences" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /me/label-preferences"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Validate Terraform**

```bash
cd infra && terraform fmt && terraform validate && cd ..
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add infra/api_gateway.tf
git commit -m "feat(infra): register label preference routes in API Gateway"
```

---

### Task 1.8: OpenAPI — extend schemas and add new routes

**Files:**
- Modify: `scripts/generate_openapi.py`
- Regen: `docs/api/openapi.yaml`

- [ ] **Step 1: Extend `LABEL_SUMMARY`**

Add `my_preference` to the `properties` map (after `info`):

```python
LABEL_SUMMARY = {
    "type": "object",
    "required": ["id", "name", "style", "status", "track_count"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "style": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["none", "queued", "running", "completed", "failed", "outdated"],
        },
        "track_count": {"type": "integer"},
        "info": {
            # ... existing block, unchanged ...
        },
        "my_preference": {
            "type": ["string", "null"],
            "enum": ["liked", "disliked", None],
        },
    },
}
```

- [ ] **Step 2: Replace `LABEL_DETAIL_RESPONSE`**

It currently uses `additionalProperties: True`. Make `my_preference` explicit so the generated TS type carries it:

```python
LABEL_DETAIL_RESPONSE = {
    "type": "object",
    "description": "Sanitized LabelInfo (admin-only fields stripped) plus my_preference.",
    "properties": {
        "my_preference": {
            "type": ["string", "null"],
            "enum": ["liked", "disliked", None],
        },
    },
    "additionalProperties": True,
}
```

- [ ] **Step 3: Add `my` query param to the existing `/labels` route**

Find the `"/labels"` route entry in `ROUTES`. Append to its `parameters` list:

```python
{
    "name": "my",
    "in": "query",
    "schema": {
        "type": "string",
        "enum": ["all", "liked", "disliked", "unrated"],
        "default": "all",
    },
},
```

- [ ] **Step 4: Add the two new routes**

Append to `ROUTES` (before the closing bracket — match the existing style):

```python
    # ── user label preferences ───────────────────────────────────────
    {
        "method": "put",
        "path": "/labels/{label_id}/preference",
        "auth": AUTH,
        "summary": "Set or clear the current user's label preference.",
        "description": (
            "Body: {\"status\": \"liked\" | \"disliked\" | \"none\"}. "
            "\"none\" deletes the row. Returns 204."
        ),
        "parameters": [
            {
                "name": "label_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["status"],
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["liked", "disliked", "none"],
                            }
                        },
                    }
                }
            },
        },
        "responses": {
            "204": {"description": "Preference updated."},
            "404": _error(404, "label_not_found."),
            "422": _error(422, "invalid status."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/me/label-preferences",
        "auth": AUTH,
        "summary": "List the current user's labelled labels.",
        "parameters": [
            {
                "name": "status",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["liked", "disliked"],
                    "default": "liked",
                },
            },
            {
                "name": "page",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "default": 1},
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Paginated user label preferences.",
                {"$ref": "#/components/schemas/MyLabelPreferencesResponse"},
            ),
            **COMMON_AUTH_ERRORS,
        },
    },
```

- [ ] **Step 5: Add `MY_LABEL_PREFERENCES_RESPONSE` schema and register it**

Add the schema near other label schemas:

```python
MY_LABEL_PREFERENCES_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "page", "limit"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "my_preference"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "my_preference": {
                        "type": "string",
                        "enum": ["liked", "disliked"],
                    },
                },
            },
        },
        "total": {"type": "integer"},
        "page": {"type": "integer"},
        "limit": {"type": "integer"},
    },
}
```

Then register it in the `schemas` dict (search for `"LabelSummary": LABEL_SUMMARY` around line 2558):

```python
"MyLabelPreferencesResponse": MY_LABEL_PREFERENCES_RESPONSE,
```

- [ ] **Step 6: Regenerate `openapi.yaml`**

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
```

Expected: `docs/api/openapi.yaml` updated.

- [ ] **Step 7: Sanity-check the regen**

```bash
grep -E "/labels/\{label_id\}/preference:|/me/label-preferences:|my_preference:|MyLabelPreferencesResponse:" docs/api/openapi.yaml | head
```

Expected: all five tokens appear.

- [ ] **Step 8: Commit**

```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml
git commit -m "$(cat <<'EOF'
feat(api): document label preference endpoints

Project my_preference on LabelSummary and LabelDetail. Add PUT
/labels/{label_id}/preference and GET /me/label-preferences. Add
?my=all|liked|disliked|unrated query param on GET /labels.
EOF
)"
```

---

### Task 1.9: Integration test for the full PUT → GET round trip

**Files:**
- Create: `tests/integration/test_user_label_prefs_e2e.py`

This test wires a `FakeDataApi` (already present in the unit-test file pattern) to verify that PUT preserves state across a subsequent GET. Aurora is not required.

- [ ] **Step 1: Write the test**

```python
"""PUT /labels/{id}/preference + GET /labels/{id} round trip."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock


def _event(route: str, *, body: dict | None = None,
           path: dict | None = None, qs: dict | None = None) -> dict:
    return {
        "routeKey": route,
        "pathParameters": path or {},
        "queryStringParameters": qs or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


def test_put_then_get_label_returns_my_preference(monkeypatch):
    """The user sets a preference; the next GET surfaces it."""
    from collector import handler

    state: dict[tuple[str, str], str] = {}

    fake_repo = MagicMock()
    fake_repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}

    def upsert(*, user_id: str, label_id: str, status: str) -> None:
        state[(user_id, label_id)] = status

    def delete(*, user_id: str, label_id: str) -> None:
        state.pop((user_id, label_id), None)

    def get_for_user(label_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        return {
            "label_name": "Fokuz",
            "my_preference": state.get((user_id, label_id)),
        }

    fake_repo.upsert_user_label_pref.side_effect = upsert
    fake_repo.delete_user_label_pref.side_effect = delete
    fake_repo.get_label_info_for_user.side_effect = get_for_user
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    # 1. Start unrated → GET shows my_preference None.
    resp = handler.lambda_handler(
        _event("GET /labels/{label_id}", path={"label_id": "lbl-1"}), None,
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["my_preference"] is None

    # 2. PUT liked → 204.
    resp = handler.lambda_handler(
        _event(
            "PUT /labels/{label_id}/preference",
            body={"status": "liked"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204

    # 3. GET reflects new state.
    resp = handler.lambda_handler(
        _event("GET /labels/{label_id}", path={"label_id": "lbl-1"}), None,
    )
    assert json.loads(resp["body"])["my_preference"] == "liked"

    # 4. PUT none → state cleared.
    resp = handler.lambda_handler(
        _event(
            "PUT /labels/{label_id}/preference",
            body={"status": "none"},
            path={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 204
    resp = handler.lambda_handler(
        _event("GET /labels/{label_id}", path={"label_id": "lbl-1"}), None,
    )
    assert json.loads(resp["body"])["my_preference"] is None
```

- [ ] **Step 2: Verify it passes**

```bash
pytest tests/integration/test_user_label_prefs_e2e.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Run full backend test suite as a gate**

```bash
pytest tests/unit tests/integration -q
```

Expected: every test green.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_user_label_prefs_e2e.py
git commit -m "test(backend): e2e label preference round trip"
```

---

## Phase 2 — Frontend types + nav

**Sequential.** Tasks 2.1 → 2.4 in order. Task 2.1 must precede every later frontend task because the regenerated `schema.d.ts` is needed for type-safe API calls.

### Task 2.1: Regenerate `frontend/src/api/schema.d.ts`

**Files:**
- Regen: `frontend/src/api/schema.d.ts`

- [ ] **Step 1: Regenerate**

```bash
cd frontend && pnpm install --frozen-lockfile 2>&1 | tail -1 && pnpm api:types && cd ..
```

Expected: `schema.d.ts` updated with new routes and the `my_preference` property on `LabelSummary` / `LabelDetail`.

- [ ] **Step 2: Verify the new types are present**

```bash
grep -E "my_preference|/labels/\{label_id\}/preference|/me/label-preferences" frontend/src/api/schema.d.ts | head
```

Expected: at least four matches.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/schema.d.ts
git commit -m "feat(frontend): regen OpenAPI types for label preferences"
```

---

### Task 2.2: Icons + i18n keys

**Files:**
- Modify: `frontend/src/components/icons.ts`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add icon re-exports**

Replace the import block in `frontend/src/components/icons.ts` with the additions (`IconBook`, `IconHeart`, `IconHeartFilled`):

```ts
export {
  IconHome,
  IconCategory,
  IconLayoutColumns,
  IconAdjustments,
  IconUser,
  IconPlayerPlay,
  IconPlayerPlayFilled,
  IconPlayerPause,
  IconPlayerSkipForward,
  IconPlayerSkipBack,
  IconChevronUp,
  IconChevronDown,
  IconDots,
  IconCopy,
  IconLogout,
  IconLoader,
  IconAlertTriangle,
  IconArrowLeft,
  IconKeyboard,
  IconArrowsExchange,
  IconDotsVertical,
  IconTrash,
  IconPlaylist,
  IconPlus,
  IconSearch,
  IconX,
  IconExternalLink,
  IconShield,
  IconBolt,
  IconBook,
  IconHeart,
  IconHeartFilled,
} from '@tabler/icons-react';
```

- [ ] **Step 2: Add i18n keys**

In `frontend/src/i18n/en.json`, inside the `appshell` object (around line 12–21), add `"library": "Library"` so the section becomes:

```json
  "appshell": {
    "admin": "Admin",
    "home": "Home",
    "categories": "Categories",
    "triage": "Triage",
    "curate": "Curate",
    "playlists": "Playlists",
    "library": "Library",
    "profile": "Profile",
    "wordmark": "CLOUDER"
  },
```

In the same file, inside `library` (after `entity_tabs`), add `prefs` and extend `list` with filter labels + the `my` column. Replace the `list` block to include the new keys and add `prefs` after `entity_tabs`:

```json
    "list": {
      "title": "Labels",
      "empty_filter": "No labels match these filters.",
      "info_pending": "Info pending",
      "search_label": "Search",
      "search_placeholder": "Search labels...",
      "style_label": "Style",
      "sort_label": "Sort",
      "sort_name": "Name (A→Z)",
      "sort_recent": "Recently updated",
      "load_more": "Load more",
      "col_name": "Label",
      "col_country": "Country",
      "col_founded": "Founded",
      "col_tracks": "Tracks",
      "col_ai_detected": "AI detected",
      "col_my": "My",
      "col_description": "Description",
      "my_filter_label": "My",
      "my_all": "All",
      "my_liked": "Liked",
      "my_disliked": "Disliked",
      "my_unrated": "Unrated"
    },
    "entity_tabs": {
      "labels": "Labels",
      "artists": "Artists",
      "artists_coming_soon": "Coming soon"
    },
    "prefs": {
      "like_aria": "Like label",
      "dislike_aria": "Dislike label",
      "unset_aria": "Remove preference"
    },
```

- [ ] **Step 3: Verify lint + typecheck**

```bash
cd frontend && pnpm typecheck && pnpm lint && cd ..
```

Expected: no new errors (pre-existing warnings about `useCurateSession` and `theme.ts` are acceptable — they predate this work).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/icons.ts frontend/src/i18n/en.json
git commit -m "feat(frontend): add Library icon + label preference i18n"
```

---

### Task 2.3: Navbar — Library link

**Files:**
- Modify: `frontend/src/routes/_layout.tsx`

- [ ] **Step 1: Update the `NAV_ITEMS` constant and the icon import**

Find the `import` for icons (currently lines ~7–15) and add `IconBook`:

```ts
import {
  IconHome,
  IconCategory,
  IconLayoutColumns,
  IconAdjustments,
  IconPlaylist,
  IconBook,
  IconUser,
  IconShield,
} from '../components/icons';
```

Replace the `NAV_ITEMS` array (lines 27–34) with:

```ts
const NAV_ITEMS: NavItem[] = [
  { path: '/', labelKey: 'appshell.home', Icon: IconHome },
  { path: '/categories', labelKey: 'appshell.categories', Icon: IconCategory },
  { path: '/triage', labelKey: 'appshell.triage', Icon: IconLayoutColumns },
  { path: '/curate', labelKey: 'appshell.curate', Icon: IconAdjustments },
  { path: '/playlists', labelKey: 'appshell.playlists', Icon: IconPlaylist },
  { path: '/library', labelKey: 'appshell.library', Icon: IconBook },
  { path: '/profile', labelKey: 'appshell.profile', Icon: IconUser },
];
```

- [ ] **Step 2: Verify build**

```bash
cd frontend && pnpm typecheck && cd ..
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/_layout.tsx
git commit -m "feat(frontend): add Library link to main navbar"
```

---

### Task 2.4: `useSetLabelPreference` hook + tests

**Files:**
- Create: `frontend/src/features/library/hooks/useSetLabelPreference.ts`
- Test: `frontend/src/features/library/hooks/__tests__/useSetLabelPreference.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/library/hooks/__tests__/useSetLabelPreference.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useSetLabelPreference } from '../useSetLabelPreference';

function wrap(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe('useSetLabelPreference', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('patches labelInfo cache optimistically and on success', async () => {
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    qc.setQueryData(['labelInfo', 'lbl-1'], { label_name: 'Fokuz', my_preference: null });

    const { result } = renderHook(() => useSetLabelPreference(), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({ labelId: 'lbl-1', status: 'liked' });
    });

    const cached = qc.getQueryData<{ my_preference: string | null }>(['labelInfo', 'lbl-1']);
    expect(cached?.my_preference).toBe('liked');
  });

  it('rolls back labelInfo on error', async () => {
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', () =>
        HttpResponse.json({ error_code: 'boom', message: 'no' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    qc.setQueryData(['labelInfo', 'lbl-1'], { label_name: 'Fokuz', my_preference: null });

    const { result } = renderHook(() => useSetLabelPreference(), { wrapper: wrap(qc) });
    await act(async () => {
      try {
        await result.current.mutateAsync({ labelId: 'lbl-1', status: 'liked' });
      } catch {
        // expected
      }
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = qc.getQueryData<{ my_preference: string | null }>(['labelInfo', 'lbl-1']);
    expect(cached?.my_preference).toBeNull();
  });
});
```

- [ ] **Step 2: Verify the test fails**

```bash
cd frontend && pnpm test -- --run src/features/library/hooks/__tests__/useSetLabelPreference.test.tsx 2>&1 | tail -10
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write the hook**

`frontend/src/features/library/hooks/useSetLabelPreference.ts`:

```ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { labelInfoKey } from './useLabelInfo';

export type LabelPreference = 'liked' | 'disliked' | null;
export type PreferenceMutationStatus = 'liked' | 'disliked' | 'none';

interface Variables {
  labelId: string;
  status: PreferenceMutationStatus;
}

interface InfoSnapshot {
  key: readonly unknown[];
  data: unknown;
}

export function useSetLabelPreference() {
  const qc = useQueryClient();
  return useMutation<void, Error, Variables, { snapshots: InfoSnapshot[] }>({
    mutationFn: ({ labelId, status }) =>
      api<void>(`/labels/${labelId}/preference`, {
        method: 'PUT',
        body: JSON.stringify({ status }),
      }),
    onMutate: ({ labelId, status }) => {
      const next: LabelPreference = status === 'none' ? null : status;
      const snapshots: InfoSnapshot[] = [];

      // labelInfo: single keyed query.
      const infoKey = labelInfoKey(labelId);
      const infoData = qc.getQueryData(infoKey);
      if (infoData !== undefined) {
        snapshots.push({ key: infoKey, data: infoData });
        qc.setQueryData(infoKey, {
          ...(infoData as Record<string, unknown>),
          my_preference: next,
        });
      }

      // labelsList: many queries — patch the matching row in each.
      const listEntries = qc.getQueriesData<{ items?: Array<Record<string, unknown>> }>({
        queryKey: ['library', 'labels'],
      });
      for (const [key, data] of listEntries) {
        if (!data || !Array.isArray(data.items)) continue;
        const hit = data.items.some((it) => (it as { id?: string }).id === labelId);
        if (!hit) continue;
        snapshots.push({ key, data });
        qc.setQueryData(key, {
          ...data,
          items: data.items.map((it) =>
            (it as { id?: string }).id === labelId
              ? { ...it, my_preference: next }
              : it,
          ),
        });
      }

      return { snapshots };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      for (const snap of ctx.snapshots) {
        qc.setQueryData(snap.key, snap.data);
      }
    },
    onSettled: (_data, _err, { labelId }) => {
      void qc.invalidateQueries({ queryKey: labelInfoKey(labelId) });
    },
  });
}
```

- [ ] **Step 4: Verify the tests pass**

```bash
cd frontend && pnpm test -- --run src/features/library/hooks/__tests__/useSetLabelPreference.test.tsx 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/library/hooks/useSetLabelPreference.ts frontend/src/features/library/hooks/__tests__/useSetLabelPreference.test.tsx
git commit -m "feat(frontend): useSetLabelPreference mutation hook"
```

---

## Phase 3 — Shared component

### Task 3.1: `LabelPreferenceButtons`

**Files:**
- Create: `frontend/src/features/library/components/LabelPreferenceButtons.tsx`
- Test: `frontend/src/features/library/components/__tests__/LabelPreferenceButtons.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/library/components/__tests__/LabelPreferenceButtons.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { LabelPreferenceButtons } from '../LabelPreferenceButtons';

function renderButtons(current: 'liked' | 'disliked' | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <LabelPreferenceButtons labelId="lbl-1" current={current} />
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LabelPreferenceButtons', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
  });

  it('renders heart and cross icons with i18n aria labels', () => {
    renderButtons(null);
    expect(screen.getByRole('button', { name: /like label/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dislike label/i })).toBeInTheDocument();
  });

  it('clicking heart on null state issues liked PUT', async () => {
    let capturedBody: unknown = null;
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', async ({ request }) => {
        capturedBody = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderButtons(null);
    fireEvent.click(screen.getByRole('button', { name: /like label/i }));
    await waitFor(() => expect(capturedBody).toEqual({ status: 'liked' }));
  });

  it('clicking active heart issues none PUT', async () => {
    let capturedBody: unknown = null;
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', async ({ request }) => {
        capturedBody = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderButtons('liked');
    fireEvent.click(screen.getByRole('button', { name: /remove preference/i }));
    await waitFor(() => expect(capturedBody).toEqual({ status: 'none' }));
  });
});
```

- [ ] **Step 2: Verify the tests fail**

```bash
cd frontend && pnpm test -- --run src/features/library/components/__tests__/LabelPreferenceButtons.test.tsx 2>&1 | tail -10
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

`frontend/src/features/library/components/LabelPreferenceButtons.tsx`:

```tsx
import { ActionIcon, Group } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconHeart, IconHeartFilled, IconX } from '../../../components/icons';
import {
  useSetLabelPreference,
  type LabelPreference,
} from '../hooks/useSetLabelPreference';

interface Props {
  labelId: string;
  current: LabelPreference;
  size?: 'sm' | 'md';
}

export function LabelPreferenceButtons({ labelId, current, size = 'sm' }: Props) {
  const { t } = useTranslation();
  const mutation = useSetLabelPreference();

  const iconSize = size === 'md' ? 18 : 14;
  const liked = current === 'liked';
  const disliked = current === 'disliked';

  const onLike = () =>
    mutation.mutate({ labelId, status: liked ? 'none' : 'liked' });
  const onDislike = () =>
    mutation.mutate({ labelId, status: disliked ? 'none' : 'disliked' });

  return (
    <Group gap={4} wrap="nowrap">
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onLike}
        aria-label={liked ? t('library.prefs.unset_aria') : t('library.prefs.like_aria')}
      >
        {liked ? (
          <IconHeartFilled size={iconSize} color="var(--mantine-color-red-6)" />
        ) : (
          <IconHeart size={iconSize} />
        )}
      </ActionIcon>
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onDislike}
        aria-label={disliked ? t('library.prefs.unset_aria') : t('library.prefs.dislike_aria')}
      >
        <IconX
          size={iconSize}
          color={disliked ? 'var(--mantine-color-dark-9)' : undefined}
        />
      </ActionIcon>
    </Group>
  );
}
```

- [ ] **Step 4: Verify the tests pass**

```bash
cd frontend && pnpm test -- --run src/features/library/components/__tests__/LabelPreferenceButtons.test.tsx 2>&1 | tail -10
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/library/components/LabelPreferenceButtons.tsx frontend/src/features/library/components/__tests__/LabelPreferenceButtons.test.tsx
git commit -m "feat(frontend): shared LabelPreferenceButtons component"
```

---

## Phase 4 — Frontend surfaces

After Phase 3, tasks 4.1 through 4.5 touch disjoint files and may run in parallel.

### Task 4.1: `LabelDetailHeader` — preference buttons next to AI badge

**Files:**
- Modify: `frontend/src/features/library/components/LabelDetailHeader.tsx`

- [ ] **Step 1: Update the component**

Replace the file with:

```tsx
import { Group, Title, Text, Anchor, Badge, Tooltip } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';
import { LabelPreferenceButtons } from './LabelPreferenceButtons';

interface Props {
  info: LabelDetail;
  styleId: string;
  labelId: string;
}

const AI_COLOR: Record<string, string> = {
  none_detected: 'green',
  unknown: 'gray',
  suspected: 'yellow',
  confirmed: 'red',
};

function formatAiContent(value: string): string {
  return `AI ${value.toUpperCase()}`;
}

export function LabelDetailHeader({ info, styleId, labelId }: Props) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const labelName = typeof rec.label_name === 'string' ? rec.label_name : '';
  const country = typeof rec.country === 'string' ? rec.country : '';
  const foundedYear =
    typeof rec.founded_year === 'number' ? rec.founded_year : null;
  const aiContent = typeof rec.ai_content === 'string' ? rec.ai_content : '';
  const aiReasoning =
    typeof rec.ai_reasoning === 'string' ? rec.ai_reasoning : '';
  const myPreference =
    rec.my_preference === 'liked' || rec.my_preference === 'disliked'
      ? rec.my_preference
      : null;

  const aiBadge = aiContent ? (
    <Tooltip
      label={aiReasoning || t('library.detail.ai_reasoning_missing')}
      multiline
      w={340}
      withinPortal
      events={{ hover: true, focus: true, touch: true }}
      styles={{
        tooltip: {
          backgroundColor: 'white',
          color: 'black',
          padding: '12px 16px',
          lineHeight: 1.5,
          border: '1px solid var(--mantine-color-gray-3)',
          boxShadow: 'var(--mantine-shadow-md)',
        },
      }}
    >
      <Badge
        color={AI_COLOR[aiContent] ?? 'gray'}
        variant="light"
        style={{ cursor: 'help' }}
      >
        {formatAiContent(aiContent)}
      </Badge>
    </Tooltip>
  ) : null;

  return (
    <>
      <Anchor component={Link} to={`/library/${styleId}`} size="sm">
        ← {t('library.detail.back_to_list', { style: styleId })}
      </Anchor>
      <Group gap="sm" mt="xs" align="center" wrap="wrap">
        <Title order={2}>{labelName}</Title>
        {aiBadge}
        <LabelPreferenceButtons labelId={labelId} current={myPreference} size="md" />
      </Group>
      <Group gap="xs" mt="xs">
        {country && (
          <Text>
            {countryFlag(country)} {country}
          </Text>
        )}
        {foundedYear !== null && (
          <Text c="dimmed">
            · {t('library.detail.founded', { year: foundedYear })}
          </Text>
        )}
      </Group>
    </>
  );
}
```

- [ ] **Step 2: Pass `labelId` from the route**

In `frontend/src/features/library/routes/LabelDetailPage.tsx`, update the call site:

```tsx
<LabelDetailHeader info={info} styleId={styleId} labelId={labelId} />
```

- [ ] **Step 3: Run the existing LabelDetailHeader tests**

```bash
cd frontend && pnpm test -- --run src/features/library 2>&1 | tail -20
```

Expected: every test still passes. Any test that asserts on the header API now needs to pass `labelId="lbl-1"`. Update tests as needed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/library/components/LabelDetailHeader.tsx frontend/src/features/library/routes/LabelDetailPage.tsx
git commit -m "feat(frontend): preference buttons in LabelDetailHeader"
```

---

### Task 4.2: `LabelsTable` — `My` column

**Files:**
- Modify: `frontend/src/features/library/components/LabelsTable.tsx`

- [ ] **Step 1: Edit the component**

Replace the file with:

```tsx
import {
  Table,
  Anchor,
  Group,
  Text,
  Center,
  Pagination,
  Skeleton,
} from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { LabelSummary } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';
import { truncateTagline } from '../lib/formatLabel';
import { LabelPreferenceButtons } from './LabelPreferenceButtons';

interface Props {
  items: LabelSummary[];
  styleId: string;
  isLoading: boolean;
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
}

export function LabelsTable(p: Props) {
  const { t } = useTranslation();

  if (p.isLoading && p.items.length === 0) {
    return <Skeleton height={320} />;
  }

  if (p.items.length === 0) {
    return (
      <Center mt="lg">
        <Text c="dimmed">{t('library.list.empty_filter')}</Text>
      </Center>
    );
  }

  return (
    <>
      <Table verticalSpacing="sm" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('library.list.col_name')}</Table.Th>
            <Table.Th>{t('library.list.col_country')}</Table.Th>
            <Table.Th>{t('library.list.col_founded')}</Table.Th>
            <Table.Th>{t('library.list.col_tracks')}</Table.Th>
            <Table.Th>{t('library.list.col_ai_detected')}</Table.Th>
            <Table.Th>{t('library.list.col_my')}</Table.Th>
            <Table.Th>{t('library.list.col_description')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {p.items.map((it) => {
            const info = it.info ?? null;
            const aiContent = info?.ai_content ? info.ai_content.toUpperCase() : null;
            const myPref =
              it.my_preference === 'liked' || it.my_preference === 'disliked'
                ? it.my_preference
                : null;
            return (
              <Table.Tr key={it.id}>
                <Table.Td>
                  <Anchor component={Link} to={`/library/${p.styleId}/labels/${it.id}`} fw={500}>
                    {it.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  {info?.country ? (
                    <Group gap={4} wrap="nowrap">
                      <Text>{countryFlag(info.country)}</Text>
                      <Text size="sm">{info.country}</Text>
                    </Group>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  {info?.founded_year ? (
                    <Text size="sm">{info.founded_year}</Text>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{it.track_count}</Text>
                </Table.Td>
                <Table.Td>
                  {aiContent ? (
                    <Text size="sm">{aiContent}</Text>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <LabelPreferenceButtons labelId={it.id} current={myPref} size="sm" />
                </Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={2} maw={420}>
                    {info?.tagline ? truncateTagline(info.tagline, 220) : '—'}
                  </Text>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      {p.pageCount > 1 && (
        <Center mt="md">
          <Pagination
            total={p.pageCount}
            value={p.page}
            onChange={p.onPageChange}
            withEdges
          />
        </Center>
      )}
    </>
  );
}
```

- [ ] **Step 2: Write a small test for the new column**

`frontend/src/features/library/components/__tests__/LabelsTable.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../../../i18n';
import { tokenStore } from '../../../../auth/tokenStore';
import { LabelsTable } from '../LabelsTable';

function renderTable(items: any[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <LabelsTable
              items={items}
              styleId="dnb"
              isLoading={false}
              page={1}
              pageCount={1}
              onPageChange={() => {}}
            />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LabelsTable My column', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders preference buttons in each row', () => {
    renderTable([
      {
        id: 'lbl-1', name: 'Fokuz', style: 'dnb', status: 'completed',
        track_count: 142, info: { tagline: 't', country: 'NL', founded_year: 2007,
          primary_styles: ['liquid'], activity: 'steady',
          ai_content: 'none_detected', updated_at: '2026-05-19T00:00:00Z',
        },
        my_preference: 'liked',
      },
    ]);
    expect(screen.getByText('My')).toBeInTheDocument();
    // active heart → aria switches to "Remove preference"
    expect(screen.getByRole('button', { name: /remove preference/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Verify the test passes + run all library tests**

```bash
cd frontend && pnpm test -- --run src/features/library 2>&1 | tail -20
```

Expected: every test green. If the existing `LabelCard.test.tsx` fixtures now need `my_preference`, the TS compiler may flag it — add `my_preference: null` to those fixtures.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/library/components/LabelsTable.tsx frontend/src/features/library/components/__tests__/LabelsTable.test.tsx
git commit -m "feat(frontend): My column on labels table"
```

---

### Task 4.3: `LibraryFilters` + `useLabelsList` + `LibraryListPage` — `my` filter

**Files:**
- Modify: `frontend/src/features/library/components/LibraryFilters.tsx`
- Modify: `frontend/src/features/library/hooks/useLabelsList.ts`
- Modify: `frontend/src/features/library/routes/LibraryListPage.tsx`

- [ ] **Step 1: Update `useLabelsList` to accept and forward `my`**

Replace the file with:

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { LabelsListResponse } from '../../../api/labels';

export type LabelsListMy = 'all' | 'liked' | 'disliked' | 'unrated';

export interface UseLabelsListParams {
  styleId: string;
  q: string;
  sort: 'name' | 'recent';
  page: number;
  limit: number;
  my: LabelsListMy;
}

export const labelsListKey = (params: UseLabelsListParams) =>
  [
    'library',
    'labels',
    params.styleId,
    params.q,
    params.sort,
    params.my,
    params.page,
    params.limit,
  ] as const;

export function useLabelsList(params: UseLabelsListParams) {
  return useQuery<LabelsListResponse, Error>({
    queryKey: labelsListKey(params),
    queryFn: () => {
      const qs = new URLSearchParams();
      if (params.styleId) qs.set('style', params.styleId);
      if (params.q) qs.set('q', params.q);
      qs.set('sort', params.sort);
      if (params.my !== 'all') qs.set('my', params.my);
      qs.set('page', String(params.page));
      qs.set('limit', String(params.limit));
      return api<LabelsListResponse>(`/labels?${qs.toString()}`);
    },
    placeholderData: (prev) => prev,
  });
}
```

- [ ] **Step 2: Update `LibraryFilters` to render a `my` SegmentedControl**

Replace the file with:

```tsx
import { Group, TextInput, Select, SegmentedControl, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useState, useEffect } from 'react';
import type { LabelsListMy } from '../hooks/useLabelsList';

export interface StyleOption {
  value: string;
  label: string;
}

interface Props {
  q: string;
  sort: 'name' | 'recent';
  styleId: string;
  styleOptions: ReadonlyArray<StyleOption>;
  stylesLoading?: boolean;
  my: LabelsListMy;
  onQChange: (q: string) => void;
  onSortChange: (sort: 'name' | 'recent') => void;
  onStyleChange: (styleId: string) => void;
  onMyChange: (my: LabelsListMy) => void;
}

export function LibraryFilters({
  q,
  sort,
  styleId,
  styleOptions,
  stylesLoading,
  my,
  onQChange,
  onSortChange,
  onStyleChange,
  onMyChange,
}: Props) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(q);

  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    const id = setTimeout(() => {
      if (draft !== q) onQChange(draft);
    }, 250);
    return () => clearTimeout(id);
  }, [draft, q, onQChange]);

  return (
    <Group gap="sm" align="end" wrap="wrap">
      <Select
        label={t('library.list.style_label')}
        value={styleId}
        onChange={(v) => v && onStyleChange(v)}
        data={styleOptions as StyleOption[]}
        disabled={stylesLoading}
        style={{ minWidth: 200 }}
      />
      <TextInput
        label={t('library.list.search_label')}
        placeholder={t('library.list.search_placeholder')}
        value={draft}
        onChange={(e) => setDraft(e.currentTarget.value)}
        style={{ minWidth: 240, flex: 1 }}
      />
      <Select
        label={t('library.list.sort_label')}
        value={sort}
        data={[
          { value: 'name', label: t('library.list.sort_name') },
          { value: 'recent', label: t('library.list.sort_recent') },
        ]}
        onChange={(v) => v && onSortChange(v as 'name' | 'recent')}
        style={{ minWidth: 180 }}
      />
      <Stack gap={4}>
        <Text size="xs" c="dimmed">
          {t('library.list.my_filter_label')}
        </Text>
        <SegmentedControl
          value={my}
          onChange={(v) => onMyChange(v as LabelsListMy)}
          data={[
            { value: 'all', label: t('library.list.my_all') },
            { value: 'liked', label: t('library.list.my_liked') },
            { value: 'disliked', label: t('library.list.my_disliked') },
            { value: 'unrated', label: t('library.list.my_unrated') },
          ]}
        />
      </Stack>
    </Group>
  );
}
```

- [ ] **Step 3: Update `LibraryListPage`**

Replace the body of `frontend/src/features/library/routes/LibraryListPage.tsx`:

```tsx
import { Container, Stack, Title } from '@mantine/core';
import { useParams, useSearchParams, Navigate, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useMemo } from 'react';
import { useLabelsList, type LabelsListMy } from '../hooks/useLabelsList';
import { EntityTabs } from '../components/EntityTabs';
import { LibraryFilters, type StyleOption } from '../components/LibraryFilters';
import { LabelsTable } from '../components/LabelsTable';
import { useStyles } from '../../../hooks/useStyles';
import { slugifyStyle } from '../lib/slugifyStyle';

const PAGE_SIZE = 25;
const MY_VALUES: ReadonlySet<LabelsListMy> = new Set(['all', 'liked', 'disliked', 'unrated']);

function readMy(raw: string | null): LabelsListMy {
  if (raw && MY_VALUES.has(raw as LabelsListMy)) return raw as LabelsListMy;
  return 'all';
}

export function LibraryListPage() {
  const { t } = useTranslation();
  const { styleId } = useParams<{ styleId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const q = searchParams.get('q') ?? '';
  const rawSort = searchParams.get('sort');
  const sort: 'name' | 'recent' = rawSort === 'recent' ? 'recent' : 'name';
  const my = readMy(searchParams.get('my'));
  const pageParam = Number(searchParams.get('page') ?? '1');
  const page = Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1;

  const stylesQuery = useStyles();
  const styleOptions: ReadonlyArray<StyleOption> = useMemo(
    () =>
      stylesQuery.data?.items.map((s) => ({
        value: slugifyStyle(s.name),
        label: s.name,
      })) ?? [],
    [stylesQuery.data],
  );
  const query = useLabelsList({
    styleId: styleId ?? '',
    q,
    sort,
    page,
    limit: PAGE_SIZE,
    my,
  });

  if (!styleId) return <Navigate to="/library" replace />;
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const updateParam = (key: string, value: string, resetPage = false) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (resetPage) next.delete('page');
    setSearchParams(next, { replace: true });
  };

  const onStyleChange = (nextSlug: string) => {
    if (nextSlug === styleId) return;
    const next = new URLSearchParams(searchParams);
    next.delete('page');
    const qs = next.toString();
    navigate(`/library/${nextSlug}${qs ? `?${qs}` : ''}`);
  };

  const onPageChange = (nextPage: number) => {
    const next = new URLSearchParams(searchParams);
    if (nextPage <= 1) next.delete('page');
    else next.set('page', String(nextPage));
    setSearchParams(next, { replace: false });
  };

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Title order={2}>{t('library.list.title')}</Title>
        <EntityTabs active="labels" styleId={styleId} />
        <LibraryFilters
          q={q}
          sort={sort}
          styleId={styleId}
          styleOptions={styleOptions}
          stylesLoading={stylesQuery.isLoading}
          my={my}
          onQChange={(v) => updateParam('q', v, true)}
          onSortChange={(v) => updateParam('sort', v, true)}
          onStyleChange={onStyleChange}
          onMyChange={(v) => updateParam('my', v === 'all' ? '' : v, true)}
        />
        <LabelsTable
          items={items}
          styleId={styleId}
          isLoading={query.isLoading}
          page={page}
          pageCount={pageCount}
          onPageChange={onPageChange}
        />
      </Stack>
    </Container>
  );
}
```

- [ ] **Step 4: Verify lib tests still green**

```bash
cd frontend && pnpm test -- --run src/features/library 2>&1 | tail -20
```

Expected: every test passes. If `useLabelsList.test.tsx` exists and references the old `UseLabelsListParams` shape, add `my: 'all'` to its fixtures.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/library/components/LibraryFilters.tsx frontend/src/features/library/hooks/useLabelsList.ts frontend/src/features/library/routes/LibraryListPage.tsx
git commit -m "feat(frontend): library 'my' filter (all/liked/disliked/unrated)"
```

---

### Task 4.4: `LabelTile` — `labelName` prop, always render, preference buttons

**Files:**
- Modify: `frontend/src/features/library/components/LabelTile.tsx`
- Modify: `frontend/src/features/library/components/__tests__/LabelTile.test.tsx`

- [ ] **Step 1: Replace the component**

```tsx
import { Anchor, ActionIcon, Badge, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLabelInfo } from '../hooks/useLabelInfo';
import { countryFlag } from '../lib/countryFlag';
import { CHANNELS } from '../lib/channelMeta';
import { LabelPreferenceButtons } from './LabelPreferenceButtons';

interface Props {
  labelId: string | null | undefined;
  labelName: string | null | undefined;
  styleId: string;
}

interface LabelInfoView {
  label_name?: string;
  country?: string | null;
  founded_year?: number | null;
  tagline?: string | null;
  summary?: string | null;
  notable_artists?: string[] | null;
  ai_content?: string | null;
  ai_reasoning?: string | null;
  my_preference?: 'liked' | 'disliked' | null;
}

function pickPreference(value: unknown): 'liked' | 'disliked' | null {
  return value === 'liked' || value === 'disliked' ? value : null;
}

export function LabelTile({ labelId, labelName, styleId }: Props) {
  const { t } = useTranslation();
  const query = useLabelInfo(labelId);

  if (!labelId) return null;

  const info = query.data as LabelInfoView | undefined;
  const detailUrl = `/library/${styleId}/labels/${labelId}`;
  const displayName = info?.label_name ?? labelName ?? '';
  const preference = pickPreference(info?.my_preference ?? null);

  // The user-facing detail endpoint now always returns 200 once a label
  // exists, but the response is `{label_name, my_preference}` when no
  // enrichment row exists. Treat such a response as "info missing" so
  // the tile stays in minimal mode (name + buttons only).
  const hasEnrichment = !!info && (
    !!info.summary ||
    !!info.tagline ||
    !!info.country ||
    info.founded_year != null ||
    (Array.isArray(info.notable_artists) && info.notable_artists.length > 0)
  );
  const showFullCard = !query.isLoading && !query.isError && hasEnrichment;

  const aiContent = info?.ai_content ?? '';
  const aiReasoning = info?.ai_reasoning ?? '';
  const notable = Array.isArray(info?.notable_artists)
    ? info!.notable_artists!.filter((a): a is string => typeof a === 'string')
    : [];
  const channels = showFullCard
    ? CHANNELS.flatMap((ch) => {
        const url = (info as Record<string, unknown>)[ch.field];
        if (typeof url !== 'string' || !url) return [];
        return [{ ...ch, url }];
      })
    : [];

  return (
    <Stack gap="sm" w={320}>
      <Group gap="sm" align="center" wrap="wrap">
        <Anchor component={Link} to={detailUrl} fw={600} size="lg">
          {displayName || labelId}
        </Anchor>
        {showFullCard && aiContent && (
          <Tooltip
            label={aiReasoning || t('library.detail.ai_reasoning_missing')}
            multiline
            w={280}
            withinPortal
            events={{ hover: true, focus: true, touch: true }}
            styles={{
              tooltip: {
                backgroundColor: 'white',
                color: 'black',
                padding: '12px 16px',
                lineHeight: 1.5,
                border: '1px solid var(--mantine-color-gray-3)',
                boxShadow: 'var(--mantine-shadow-md)',
              },
            }}
          >
            <Badge
              variant="outline"
              style={{
                cursor: 'help',
                backgroundColor: 'white',
                color: 'black',
                borderColor: 'black',
              }}
            >
              AI {aiContent.toUpperCase()}
            </Badge>
          </Tooltip>
        )}
        <LabelPreferenceButtons labelId={labelId} current={preference} size="sm" />
      </Group>
      {showFullCard && (info?.country || info?.founded_year != null) && (
        <Group gap="xs">
          {info?.country && (
            <Text size="sm">
              {countryFlag(info.country)} {info.country}
            </Text>
          )}
          {info?.founded_year != null && (
            <Text size="sm" c="dimmed">
              · {t('library.detail.founded', { year: info.founded_year })}
            </Text>
          )}
        </Group>
      )}
      {showFullCard && info?.tagline && (
        <Text size="sm" fw={500}>
          {info.tagline}
        </Text>
      )}
      {showFullCard && info?.summary && (
        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
          {info.summary}
        </Text>
      )}
      {showFullCard && notable.length > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600} c="dimmed">
            {t('library.detail.notable_artists')}
          </Text>
          <Text size="sm">{notable.join(', ')}</Text>
        </Stack>
      )}
      {channels.length > 0 && (
        <Group gap={6}>
          {channels.map((ch) => (
            <ActionIcon
              key={ch.kind}
              component="a"
              href={ch.url}
              target="_blank"
              rel="noopener noreferrer"
              variant="subtle"
              aria-label={t(ch.i18nKey)}
            >
              <ch.Icon size={16} />
            </ActionIcon>
          ))}
        </Group>
      )}
    </Stack>
  );
}
```

- [ ] **Step 2: Update the existing tile tests**

Replace `frontend/src/features/library/components/__tests__/LabelTile.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { LabelTile } from '../LabelTile';

function renderTile(labelId: string | null, labelName: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <LabelTile labelId={labelId} labelName={labelName} styleId="dnb" />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LabelTile', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders null when labelId is null', () => {
    renderTile(null);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders name + preference buttons when enrichment is missing (minimal payload)', async () => {
    server.use(
      http.get('http://localhost/labels/minimal', () =>
        HttpResponse.json({ label_name: 'Fokuz', my_preference: null }),
      ),
    );
    renderTile('minimal', 'fallback');
    await waitFor(() => expect(screen.getByText('Fokuz')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /like label/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dislike label/i })).toBeInTheDocument();
    // No tagline/summary/etc → no rich content row.
    expect(screen.queryByText('soulful d&b')).not.toBeInTheDocument();
  });

  it('renders name + preference buttons while info is still loading', () => {
    // No msw handler registered → request hangs; tile renders minimal mode
    // with the labelName fallback until the response arrives.
    renderTile('hanging', 'Pending Label');
    expect(screen.getByText('Pending Label')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /like label/i })).toBeInTheDocument();
  });

  it('renders the label name + full content when fetch succeeds', async () => {
    server.use(
      http.get('http://localhost/labels/abc', () =>
        HttpResponse.json({
          label_name: 'Fokuz',
          country: 'NL',
          tagline: 'soulful d&b',
          website: 'https://fokuzrecordings.com',
          soundcloud_url: 'https://soundcloud.com/fokuz',
          my_preference: null,
        }),
      ),
    );
    renderTile('abc', 'fallback name');
    await waitFor(() => expect(screen.getByText('Fokuz')).toBeInTheDocument());
    expect(screen.getByText('soulful d&b')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run library tests**

```bash
cd frontend && pnpm test -- --run src/features/library 2>&1 | tail -20
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/library/components/LabelTile.tsx frontend/src/features/library/components/__tests__/LabelTile.test.tsx
git commit -m "feat(frontend): always render LabelTile with preference buttons"
```

---

### Task 4.5: `CurateSession` — pass `labelName`

**Files:**
- Modify: `frontend/src/features/curate/components/CurateSession.tsx`

- [ ] **Step 1: Add the `labelName` prop**

In the JSX where `<LabelTile />` is rendered (currently around line 336), update to:

```tsx
        <LabelTile
          labelId={session.currentTrack?.label_id ?? null}
          labelName={session.currentTrack?.label_name ?? null}
          styleId={styleId}
        />
```

- [ ] **Step 2: Verify typecheck**

```bash
cd frontend && pnpm typecheck 2>&1 | tail -5
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/curate/components/CurateSession.tsx
git commit -m "feat(frontend): curate tile carries labelName fallback"
```

---

### Task 4.6: `CategoryPlayerPanel` — pass `labelName`

**Files:**
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`

- [ ] **Step 1: Update the `<LabelTile />` call**

In `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`, find the conditional render around line 263 and replace with:

```tsx
      {effectiveRich?.label?.id && (
        <LabelTile
          labelId={effectiveRich.label.id}
          labelName={effectiveRich.label.name ?? null}
          styleId={styleId}
        />
      )}
```

- [ ] **Step 2: Verify typecheck**

```bash
cd frontend && pnpm typecheck 2>&1 | tail -5
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/categories/components/CategoryPlayerPanel.tsx
git commit -m "feat(frontend): category player tile carries labelName fallback"
```

---

## Phase 5 — Verification

### Task 5.1: Full backend gate

- [ ] **Step 1: Run the entire backend test suite**

```bash
export PYTHONPATH=src
pytest tests/unit tests/integration -q
```

Expected: every test green. The total should be the prior count (~950) + the new tests from Phase 1.

- [ ] **Step 2: Confirm Terraform still validates**

```bash
cd infra && terraform validate && cd ..
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Confirm OpenAPI is up to date**

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
git diff --stat docs/api/openapi.yaml
```

Expected: no diff (Task 1.8 already committed the regen).

- [ ] **Step 4: Commit any drift, if needed**

If Step 3 shows a diff (a previous task touched routes after the regen), regenerate and commit:

```bash
git add docs/api/openapi.yaml
git commit -m "chore(api): regen openapi.yaml"
```

### Task 5.2: Full frontend gate

- [ ] **Step 1: Run all frontend tests**

```bash
cd frontend && pnpm test -- --run 2>&1 | tail -10
```

Expected: every test green.

- [ ] **Step 2: Typecheck + lint + build**

```bash
cd frontend && pnpm typecheck && pnpm lint && pnpm build 2>&1 | tail -10 && cd ..
```

Expected: no errors. Pre-existing lint warnings (`useCurateSession` deps, `theme.ts` disable directive) are acceptable.

- [ ] **Step 3: Smoke-test the dev server**

```bash
# In one terminal:
cd frontend && pnpm dev
```

Open `http://localhost:5173/library/drum-and-bass`. Verify:

- The `Library` link is visible in the navbar between Playlists and Profile.
- The labels table has a `My` column with heart + cross icons.
- The `All / Liked / Disliked / Unrated` filter is visible above the table; switching to `Liked` filters the list.
- Clicking the heart in a row flips the icon to filled red and persists across page refresh.
- Open a label detail page — the AI badge and heart/cross sit in the title row.
- Start a curate session on a track with a label — the tile shows the name + heart/cross even before label info loads.
- Click a track whose label has no enrichment yet — tile still renders the name + buttons.

### Task 5.3: Branch sanity

- [ ] **Step 1: Confirm branch state**

```bash
git rev-parse --abbrev-ref HEAD
# expected: feat/user-label-preferences

git log --oneline main..HEAD | head
```

Expected: the commits from Phase 1–4, in order.

- [ ] **Step 2: Stop here**

Per the project policy and execution arguments, do NOT push or merge. Hand the branch back to the human for review and ship.
