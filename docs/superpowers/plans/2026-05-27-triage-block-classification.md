# Triage Block Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At triage-block creation, route liked label/artist tracks to a new FAV bucket, demote disliked and compilation tracks to NOT, and expose all four rules as Advanced toggles defaulting ON.

**Architecture:** Classification stays a single `INSERT … SELECT` with a `CASE` in `TriageRepository.create_block`. Optional branches are emitted as SQL fragments gated by per-block boolean flags (persisted on `triage_blocks`); disabled toggles bind no parameters. `FAV` is a new technical bucket created automatically alongside NEW/OLD/NOT/DISCARD/UNCLASSIFIED. The pure helper `classify_bucket_type` mirrors the `CASE` for unit tests.

**Tech Stack:** Python 3 + Aurora RDS Data API (no psycopg at runtime), Alembic, Pydantic; React 19 + Mantine 9 + Zod; pytest; vitest.

**Precedence (first match wins):**
```
1. liked label   OR liked artist      -> FAV            [include_favorites]
2. disliked label OR disliked artist  -> NOT            [include_disliked_labels / include_disliked_artists]
3. spotify_release_date IS NULL       -> UNCLASSIFIED
4. spotify_release_date < old_cutoff  -> OLD
5. release_type = 'compilation'       -> NOT            [compilations_to_not]
6. else                               -> NEW
```
Likes beat dislikes (branch 1 before branch 2) — intentional.

**Conventions for this plan**
- `PYTEST` means the main-repo venv binary (worktree has no `.venv`):
  `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`
- `PY` means `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python`
- `pytest.ini` already sets `PYTHONPATH=src` for the test runner; standalone scripts need `PYTHONPATH=src` explicitly.
- Commits go through the `caveman:caveman-commit` skill (generate subject/body, then `git commit`). Never hand-write subject lines. Multi-line bodies use heredoc form.
- Work happens on branch `feat/triage-classification-flags-fav` (already created).

---

## File Structure

**Backend (modify):**
- `src/collector/curation/triage_service.py` — `BUCKET_TYPE_FAV`, technical-bucket tuples, `classify_bucket_type`.
- `src/collector/curation/schemas.py` — `CreateTriageBlockIn` three new bools + default flip.
- `src/collector/curation/triage_repository.py` — `create_block` params/persist/CASE, `TriageBlockRow`, `_fetch_block_detail`.
- `src/collector/curation_handler.py` — `_create_triage_block` forwarding, `_serialize_triage_block` response.
- `src/collector/db_models.py` — three columns + updated CHECK constraint string.
- `scripts/generate_openapi.py` — response schema booleans (request schema auto-derives from the Pydantic model).

**Backend (create):**
- `alembic/versions/20260527_27_triage_classification_flags_fav.py` — columns + CHECK migration.

**Frontend (modify):**
- `frontend/src/features/triage/lib/triageSchemas.ts` — three new bool fields + default flip.
- `frontend/src/features/triage/hooks/useCreateTriageBlock.ts` — input interface.
- `frontend/src/features/triage/components/CreateTriageBlockDialog.tsx` — initial values + three Switches.
- `frontend/src/features/triage/lib/bucketLabels.ts` — `'FAV'` in type + technical set.
- `frontend/src/i18n/en.json` — three toggle label/description pairs.
- `frontend/src/api/schema.d.ts` — regenerated.
- `docs/api/openapi.yaml` — regenerated.

**Tests (modify/create):** `tests/unit/test_triage_service.py`, `tests/unit/test_triage_schemas.py`, `tests/unit/test_triage_repository.py`, `tests/unit/test_curation_handler_triage.py`, `tests/integration/test_triage_handler.py`, `frontend/.../CreateTriageBlockDialog.test.tsx`, `frontend/.../bucketLabels.test.ts`, `frontend/.../useCreateTriageBlock.test.tsx`.

**Scope note:** the spec floated an optional `no_tracks_body_fav` empty-state string. Dropped here — FAV reuses the default bucket empty-state like NEW/OLD, avoiding an orphan i18n key and an unverified component edit.

---

## Task 1: FAV constant + classify_bucket_type (pure)

**Files:**
- Modify: `src/collector/curation/triage_service.py`
- Test: `tests/unit/test_triage_service.py`

- [ ] **Step 1: Write the failing tests**

Add `BUCKET_TYPE_FAV` to the import block at the top of `tests/unit/test_triage_service.py` (it imports names from `collector.curation.triage_service`). Then add these cases to `class TestClassifyBucketType`:

```python
    def test_favorite_is_highest_priority(self) -> None:
        # Favorite wins over disliked, OLD, compilation, and NULL date.
        assert (
            classify_bucket_type(
                spotify_release_date=None,
                release_type="compilation",
                old_cutoff=date(2026, 4, 1),
                is_favorite=True,
                is_disliked=True,
            )
            == BUCKET_TYPE_FAV
        )
        assert (
            classify_bucket_type(
                spotify_release_date=date(2020, 1, 1),
                release_type="single",
                old_cutoff=date(2026, 4, 1),
                is_favorite=True,
            )
            == BUCKET_TYPE_FAV
        )

    def test_disliked_beats_date_when_not_favorite(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2020, 1, 1),
                release_type="single",
                old_cutoff=date(2026, 4, 1),
                is_favorite=False,
                is_disliked=True,
            )
            == BUCKET_TYPE_NOT
        )

    def test_compilation_to_not_false_routes_to_new(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2026, 4, 15),
                release_type="compilation",
                old_cutoff=date(2026, 4, 1),
                compilation_to_not=False,
            )
            == BUCKET_TYPE_NEW
        )
```

Also assert FAV is technical in the existing membership test (the test around line 150 that checks `BUCKET_TYPE_* in TECHNICAL_BUCKET_TYPES`) by adding:

```python
        assert BUCKET_TYPE_FAV in TECHNICAL_BUCKET_TYPES
```

and add `BUCKET_TYPE_FAV` to that file's imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST tests/unit/test_triage_service.py -q`
Expected: FAIL — `cannot import name 'BUCKET_TYPE_FAV'` / `classify_bucket_type() got an unexpected keyword argument 'is_favorite'`.

- [ ] **Step 3: Implement in `triage_service.py`**

Add the constant after `BUCKET_TYPE_STAGING`:

```python
BUCKET_TYPE_FAV = "FAV"
```

Add FAV to both tuples:

```python
TECHNICAL_BUCKET_TYPES: tuple[str, ...] = (
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_UNCLASSIFIED,
    BUCKET_TYPE_FAV,
)

TECHNICAL_BUCKET_DISPLAY_ORDER: tuple[str, ...] = (
    BUCKET_TYPE_FAV,
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_UNCLASSIFIED,
    BUCKET_TYPE_DISCARD,
)
```

Replace `classify_bucket_type` with:

```python
def classify_bucket_type(
    *,
    spotify_release_date: date | None,
    release_type: str | None,
    old_cutoff: date,
    is_favorite: bool = False,
    is_disliked: bool = False,
    compilation_to_not: bool = True,
) -> str:
    """Pure mirror of the SQL CASE in create_block.

    Ordering (first match wins):
        is_favorite                       -> FAV   (likes beat dislikes)
        is_disliked                       -> NOT
        NULL date                         -> UNCLASSIFIED
        date < old_cutoff                 -> OLD
        compilation & compilation_to_not  -> NOT
        else                              -> NEW
    """
    if is_favorite:
        return BUCKET_TYPE_FAV
    if is_disliked:
        return BUCKET_TYPE_NOT
    if spotify_release_date is None:
        return BUCKET_TYPE_UNCLASSIFIED
    if spotify_release_date < old_cutoff:
        return BUCKET_TYPE_OLD
    if release_type == "compilation" and compilation_to_not:
        return BUCKET_TYPE_NOT
    return BUCKET_TYPE_NEW
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST tests/unit/test_triage_service.py -q`
Expected: PASS (all, including pre-existing cases).

- [ ] **Step 5: Commit** (via `caveman:caveman-commit`)

```bash
git add src/collector/curation/triage_service.py tests/unit/test_triage_service.py
git commit -m "<generated subject>"
```

---

## Task 2: Request schema flags

**Files:**
- Modify: `src/collector/curation/schemas.py:34-54`
- Test: `tests/unit/test_triage_schemas.py`

- [ ] **Step 1: Update the failing tests**

In `tests/unit/test_triage_schemas.py`, change `TestCreateTriageBlockInPopulateOptions.test_defaults_populate_options` to expect the new defaults, and add the three new fields:

```python
    def test_defaults_populate_options(self) -> None:
        m = CreateTriageBlockIn.model_validate(
            {
                "style_id": "00000000-0000-0000-0000-000000000001",
                "name": "House",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
            }
        )
        assert m.old_offset_weeks == 0
        assert m.include_disliked_labels is True
        assert m.include_disliked_artists is True
        assert m.compilations_to_not is True
        assert m.include_favorites is True
```

Add a new test asserting the three new flags can be set off:

```python
    def test_accepts_classification_flags_off(self) -> None:
        m = CreateTriageBlockIn.model_validate(
            {
                "style_id": "00000000-0000-0000-0000-000000000001",
                "name": "House",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
                "include_disliked_labels": False,
                "include_disliked_artists": False,
                "compilations_to_not": False,
                "include_favorites": False,
            }
        )
        assert m.include_disliked_labels is False
        assert m.include_disliked_artists is False
        assert m.compilations_to_not is False
        assert m.include_favorites is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST tests/unit/test_triage_schemas.py -q`
Expected: FAIL — `assert m.include_disliked_labels is True` fails (currently False); `include_disliked_artists` attribute missing.

- [ ] **Step 3: Implement in `schemas.py`**

Replace the field block in `CreateTriageBlockIn` (the `old_offset_weeks` / `include_disliked_labels` lines) with:

```python
    old_offset_weeks: int = Field(default=0, ge=0, le=520)
    include_disliked_labels: bool = Field(default=True)
    include_disliked_artists: bool = Field(default=True)
    compilations_to_not: bool = Field(default=True)
    include_favorites: bool = Field(default=True)
```

(Leave validators and `model_config = ConfigDict(extra="forbid")` unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST tests/unit/test_triage_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** (via `caveman:caveman-commit`)

```bash
git add src/collector/curation/schemas.py tests/unit/test_triage_schemas.py
git commit -m "<generated subject>"
```

---

## Task 3: DB model + migration

**Files:**
- Modify: `src/collector/db_models.py:416-418` (columns), `:456-459` (CHECK string)
- Create: `alembic/versions/20260527_27_triage_classification_flags_fav.py`

This task changes schema; verification is model import + (if a local Postgres is available) an Alembic round-trip. No unit test.

- [ ] **Step 1: Add columns to `db_models.py`**

After the existing `include_disliked_labels` column (ends at line 418), insert:

```python
    include_disliked_artists: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    compilations_to_not: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE")
    )
    include_favorites: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
```

- [ ] **Step 2: Update the bucket-type CHECK string in `db_models.py`**

Replace:

```python
        CheckConstraint(
            "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING')",
            name="ck_triage_buckets_type",
        ),
```

with:

```python
        CheckConstraint(
            "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING','FAV')",
            name="ck_triage_buckets_type",
        ),
```

- [ ] **Step 3: Create the migration**

Create `alembic/versions/20260527_27_triage_classification_flags_fav.py`:

```python
"""triage classification flags and FAV bucket

Revision ID: 20260527_27
Revises: 20260527_26
Create Date: 2026-05-27 00:00:02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260527_27"
down_revision = "20260527_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "triage_blocks",
        sa.Column(
            "include_disliked_artists",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "triage_blocks",
        sa.Column(
            "compilations_to_not",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )
    op.add_column(
        "triage_blocks",
        sa.Column(
            "include_favorites",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.drop_constraint(
        "ck_triage_buckets_type", "triage_buckets", type_="check"
    )
    op.create_check_constraint(
        "ck_triage_buckets_type",
        "triage_buckets",
        "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING','FAV')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_triage_buckets_type", "triage_buckets", type_="check"
    )
    op.create_check_constraint(
        "ck_triage_buckets_type",
        "triage_buckets",
        "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING')",
    )
    op.drop_column("triage_blocks", "include_favorites")
    op.drop_column("triage_blocks", "compilations_to_not")
    op.drop_column("triage_blocks", "include_disliked_artists")
```

Server defaults reflect historical rows: compilations were always routed to NOT (`TRUE`); disliked-artist and favorites rules did not exist (`FALSE`). New blocks always send explicit values from the API, so these defaults only affect already-finalized rows where the flags are display-only.

- [ ] **Step 4: Verify model import**

Run: `PYTHONPATH=src PY -c "import collector.db_models; print('ok')"`
Expected: prints `ok` (no SQLAlchemy mapping error).

- [ ] **Step 5: Verify the migration round-trips (requires local Postgres)**

```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/alembic upgrade head
/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/alembic downgrade -1
/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/alembic upgrade head
```
Expected: each command exits 0. If no local Postgres is available, skip and note it; the migration is exercised in the deploy pipeline.

- [ ] **Step 6: Commit** (via `caveman:caveman-commit`)

```bash
git add src/collector/db_models.py alembic/versions/20260527_27_triage_classification_flags_fav.py
git commit -m "<generated subject>"
```

---

## Task 4: Repository — create_block classification + persistence

**Files:**
- Modify: `src/collector/curation/triage_repository.py`
- Test: `tests/unit/test_triage_repository.py`

### 4a. Update existing repository-test mocks (they must reflect the FAV bucket + new columns)

- [ ] **Step 1: Patch the shared mock literals**

In `tests/unit/test_triage_repository.py`:

- Replace every occurrence of `["NEW", "OLD", "NOT", "DISCARD", "UNCLASSIFIED"]` with `["NEW", "OLD", "NOT", "DISCARD", "UNCLASSIFIED", "FAV"]` (the technical-bucket `RETURNING` mock — `create_block` now inserts six technical buckets).
- Replace every occurrence of `["NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"]` with `["FAV", "NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"]` (the buckets-with-counts / display-order mock).
- In every detail-fetch mock row that contains the line `"include_disliked_labels": <bool>,`, add immediately after it:
  ```python
                    "include_disliked_artists": False,
                    "compilations_to_not": True,
                    "include_favorites": False,
  ```

- [ ] **Step 2: Update `test_create_block_happy_path` assertions**

Replace its tail assertions with:

```python
    assert isinstance(out, TriageBlockRow)
    assert out.style_name == "House"
    assert out.status == "IN_PROGRESS"
    assert len(out.buckets) == 7
    types = [b.bucket_type for b in out.buckets]
    assert types[:6] == ["FAV", "NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"]
    assert types[6] == "STAGING"
```

- [ ] **Step 3: Update `test_dataclasses_have_expected_fields`**

In the `TriageBlockRow(...)` construction, add after `include_disliked_labels=False,`:

```python
        include_disliked_artists=False,
        compilations_to_not=True,
        include_favorites=False,
```

### 4b. New failing tests for the classification branches

- [ ] **Step 4: Add new repository tests**

Append to `tests/unit/test_triage_repository.py` (reuse the existing `_api_with_responses` helper and the six-response sequence shape from `test_create_block_classify_sql_includes_disliked_branch_and_offset`, but with the FAV bucket present). Use this helper-local builder at the top of each new test:

```python
def _create_block_responses(detail_overrides: dict[str, Any]) -> list[list[dict[str, Any]]]:
    detail = {
        "id": "b-1",
        "user_id": "u-1",
        "style_id": "s-1",
        "style_name": "House",
        "name": "X",
        "date_from": "2026-04-20",
        "date_to": "2026-04-26",
        "status": "IN_PROGRESS",
        "old_offset_weeks": 0,
        "include_disliked_labels": True,
        "include_disliked_artists": True,
        "compilations_to_not": True,
        "include_favorites": True,
        "created_at": "2026-04-28T00:00:00+00:00",
        "updated_at": "2026-04-28T00:00:00+00:00",
        "finalized_at": None,
    }
    detail.update(detail_overrides)
    return [
        [{"id": "s-1", "name": "House"}],
        [{"id": "b-1"}],
        [
            {"id": f"t-{i}", "bucket_type": t}
            for i, t in enumerate(
                ["NEW", "OLD", "NOT", "DISCARD", "UNCLASSIFIED", "FAV"]
            )
        ],
        [],   # no alive categories
        [],   # classify INSERT
        [detail],
        [],   # buckets-with-counts
    ]


def test_create_block_favorites_branch_present() -> None:
    api = _api_with_responses(_create_block_responses({}))
    repo = TriageRepository(api)
    repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="X",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
        include_favorites=True,
    )
    classify_call = api.execute.call_args_list[4]
    sql, params = classify_call.args[0], classify_call.args[1]
    assert "clouder_user_label_prefs" in sql
    assert "clouder_user_artist_prefs" in sql
    assert "ulp.status = 'liked'" in sql
    assert "uap.status = 'liked'" in sql
    assert ":fav_bucket_id" in sql
    assert "fav_bucket_id" in params


def test_create_block_disliked_artists_branch_present() -> None:
    api = _api_with_responses(_create_block_responses({}))
    repo = TriageRepository(api)
    repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="X",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
        include_disliked_artists=True,
    )
    sql = api.execute.call_args_list[4].args[0]
    assert "clouder_user_artist_prefs" in sql
    assert "uap.status = 'disliked'" in sql
    assert "cta.track_id = t.id" in sql


def test_create_block_compilation_toggle_off_omits_branch() -> None:
    api = _api_with_responses(_create_block_responses({"compilations_to_not": False}))
    repo = TriageRepository(api)
    repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="X",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
        include_disliked_labels=False,
        include_disliked_artists=False,
        include_favorites=False,
        compilations_to_not=False,
    )
    sql = api.execute.call_args_list[4].args[0]
    params = api.execute.call_args_list[4].args[1]
    assert "release_type = 'compilation'" not in sql
    assert "fav_bucket_id" not in params
    assert "not_bucket_id" not in params


def test_create_block_persists_all_flags() -> None:
    api = _api_with_responses(_create_block_responses({}))
    repo = TriageRepository(api)
    repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="X",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
        include_disliked_labels=True,
        include_disliked_artists=False,
        compilations_to_not=True,
        include_favorites=False,
    )
    (block_insert_call,) = [
        c
        for c in api.execute.call_args_list
        if "INSERT INTO triage_blocks" in c.args[0]
    ]
    p = block_insert_call.args[1]
    assert p["include_disliked_labels"] is True
    assert p["include_disliked_artists"] is False
    assert p["compilations_to_not"] is True
    assert p["include_favorites"] is False
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `PYTEST tests/unit/test_triage_repository.py -q`
Expected: FAIL — `create_block() got an unexpected keyword argument 'include_favorites'` and `KeyError: 'FAV'` (bucket map lacks FAV until step 6).

### 4c. Implement the repository changes

- [ ] **Step 6: Import the FAV constant**

In `triage_repository.py`, add `BUCKET_TYPE_FAV,` to the `from collector.curation.triage_service import (...)` list.

- [ ] **Step 7: Add fields to `TriageBlockRow`**

In the `TriageBlockRow` dataclass, after `include_disliked_labels: bool` insert:

```python
    include_disliked_artists: bool
    compilations_to_not: bool
    include_favorites: bool
```

- [ ] **Step 8: Extend `create_block` signature**

Replace the signature defaults so it reads:

```python
    def create_block(
        self,
        *,
        user_id: str,
        style_id: str,
        name: str,
        date_from: date_type,
        date_to: date_type,
        old_offset_weeks: int = 0,
        include_disliked_labels: bool = True,
        include_disliked_artists: bool = True,
        compilations_to_not: bool = True,
        include_favorites: bool = True,
    ) -> TriageBlockRow:
```

- [ ] **Step 9: Persist the new columns in the block INSERT**

Replace the `INSERT INTO triage_blocks (...) VALUES (...)` statement and its params dict with:

```python
            self._data_api.execute(
                """
                INSERT INTO triage_blocks (
                    id, user_id, style_id, name,
                    date_from, date_to, status,
                    old_offset_weeks, include_disliked_labels,
                    include_disliked_artists, compilations_to_not,
                    include_favorites,
                    created_at, updated_at
                ) VALUES (
                    :id, :user_id, :style_id, :name,
                    :date_from, :date_to, 'IN_PROGRESS',
                    :old_offset_weeks, :include_disliked_labels,
                    :include_disliked_artists, :compilations_to_not,
                    :include_favorites,
                    :now, :now
                )
                """,
                {
                    "id": block_id,
                    "user_id": user_id,
                    "style_id": style_id,
                    "name": name,
                    "date_from": date_from,
                    "date_to": date_to,
                    "old_offset_weeks": old_offset_weeks,
                    "include_disliked_labels": include_disliked_labels,
                    "include_disliked_artists": include_disliked_artists,
                    "compilations_to_not": compilations_to_not,
                    "include_favorites": include_favorites,
                    "now": now,
                },
                transaction_id=tx_id,
            )
```

- [ ] **Step 10: Replace step-5 classification with the gated CASE**

Replace the existing block that builds `disliked_when` and runs the classify INSERT (the `disliked_when = ""` through the `self._data_api.execute(...)` for `triage_bucket_tracks`) with:

```python
            # 5. Classify and insert tracks (one INSERT FROM SELECT).
            #    Branch order (first match wins): FAV, NOT(disliked),
            #    date branches, NOT(compilation), else NEW. Likes beat
            #    dislikes. Optional branches are emitted as SQL fragments so
            #    disabled toggles bind no parameters.
            fav_when = ""
            compilation_when = ""
            classify_params: dict[str, Any] = {
                "user_id": user_id,
                "style_id": style_id,
                "date_from": date_from,
                "date_to": date_to,
                "old_cutoff": old_cutoff,
                "now": now,
                "new_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_NEW],
                "old_bucket_id": tech_bucket_id_by_type[BUCKET_TYPE_OLD],
                "unclassified_bucket_id": tech_bucket_id_by_type[
                    BUCKET_TYPE_UNCLASSIFIED
                ],
            }

            if include_favorites:
                fav_when = """
                        WHEN EXISTS (
                            SELECT 1
                            FROM clouder_albums a
                            JOIN clouder_user_label_prefs ulp
                              ON ulp.label_id = a.label_id
                            WHERE a.id = t.album_id
                              AND ulp.user_id = :user_id
                              AND ulp.status = 'liked'
                        ) OR EXISTS (
                            SELECT 1
                            FROM clouder_track_artists cta
                            JOIN clouder_user_artist_prefs uap
                              ON uap.artist_id = cta.artist_id
                            WHERE cta.track_id = t.id
                              AND uap.user_id = :user_id
                              AND uap.status = 'liked'
                        ) THEN :fav_bucket_id
                """
                classify_params["fav_bucket_id"] = tech_bucket_id_by_type[
                    BUCKET_TYPE_FAV
                ]

            disliked_terms: list[str] = []
            if include_disliked_labels:
                disliked_terms.append(
                    """EXISTS (
                            SELECT 1
                            FROM clouder_albums a
                            JOIN clouder_user_label_prefs ulp
                              ON ulp.label_id = a.label_id
                            WHERE a.id = t.album_id
                              AND ulp.user_id = :user_id
                              AND ulp.status = 'disliked'
                        )"""
                )
            if include_disliked_artists:
                disliked_terms.append(
                    """EXISTS (
                            SELECT 1
                            FROM clouder_track_artists cta
                            JOIN clouder_user_artist_prefs uap
                              ON uap.artist_id = cta.artist_id
                            WHERE cta.track_id = t.id
                              AND uap.user_id = :user_id
                              AND uap.status = 'disliked'
                        )"""
                )
            disliked_when = ""
            if disliked_terms:
                disliked_when = (
                    "WHEN "
                    + " OR ".join(disliked_terms)
                    + " THEN :not_bucket_id"
                )
            if compilations_to_not:
                compilation_when = (
                    "WHEN t.release_type = 'compilation' "
                    "THEN :not_bucket_id"
                )
            if disliked_when or compilation_when:
                classify_params["not_bucket_id"] = tech_bucket_id_by_type[
                    BUCKET_TYPE_NOT
                ]

            self._data_api.execute(
                f"""
                INSERT INTO triage_bucket_tracks
                    (triage_bucket_id, track_id, added_at)
                SELECT
                    CASE
                        {fav_when}
                        {disliked_when}
                        WHEN t.spotify_release_date IS NULL
                            THEN :unclassified_bucket_id
                        WHEN t.spotify_release_date < :old_cutoff
                            THEN :old_bucket_id
                        {compilation_when}
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
                classify_params,
                transaction_id=tx_id,
            )
```

- [ ] **Step 11: Update `_fetch_block_detail` SELECT + display CASE + return**

In `_fetch_block_detail`, change the block SELECT column list line:

```python
                tb.old_offset_weeks, tb.include_disliked_labels,
```

to:

```python
                tb.old_offset_weeks, tb.include_disliked_labels,
                tb.include_disliked_artists, tb.compilations_to_not,
                tb.include_favorites,
```

Change the bucket-ordering `CASE` to put FAV first:

```python
                CASE tbk.bucket_type
                    WHEN 'FAV' THEN 0
                    WHEN 'NEW' THEN 1
                    WHEN 'OLD' THEN 2
                    WHEN 'NOT' THEN 3
                    WHEN 'UNCLASSIFIED' THEN 4
                    WHEN 'DISCARD' THEN 5
                    WHEN 'STAGING' THEN 6
                END,
```

In the `return TriageBlockRow(...)`, after `include_disliked_labels=bool(b["include_disliked_labels"]),` add:

```python
            include_disliked_artists=bool(b["include_disliked_artists"]),
            compilations_to_not=bool(b["compilations_to_not"]),
            include_favorites=bool(b["include_favorites"]),
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `PYTEST tests/unit/test_triage_repository.py -q`
Expected: PASS (existing + new). If the pre-existing `test_create_block_classify_sql_includes_disliked_branch_and_offset` or `..._includes_filters_and_case` fail on a `params`/bucket assertion, confirm they now find `ulp.status = 'disliked'` and `not_bucket_id` — these substrings still appear because those tests pass `include_disliked_labels=True`.

- [ ] **Step 13: Commit** (via `caveman:caveman-commit`)

```bash
git add src/collector/curation/triage_repository.py tests/unit/test_triage_repository.py
git commit -m "<generated subject>"
```

---

## Task 5: Handler forwarding + serialization

**Files:**
- Modify: `src/collector/curation_handler.py:1042-1083`
- Test: `tests/unit/test_curation_handler_triage.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_curation_handler_triage.py` (use the file's existing patterns for building an event and a fake `TriageRepository`; the create handler is `_create_triage_block`). Add a test that the handler forwards all four flags and serializes them:

```python
def test_create_triage_block_forwards_and_serializes_flags() -> None:
    from collector.curation_handler import (
        _create_triage_block,
        _serialize_triage_block,
    )
    from collector.curation.triage_repository import (
        TriageBlockRow,
        TriageBucketRow,
    )

    captured = {}

    class _Repo:
        def create_block(self, **kwargs):
            captured.update(kwargs)
            return TriageBlockRow(
                id="b-1",
                user_id="u-1",
                style_id="00000000-0000-0000-0000-000000000001",
                style_name="House",
                name="X",
                date_from="2026-04-20",
                date_to="2026-04-26",
                status="IN_PROGRESS",
                old_offset_weeks=0,
                include_disliked_labels=True,
                include_disliked_artists=False,
                compilations_to_not=True,
                include_favorites=False,
                created_at="2026-04-28T00:00:00+00:00",
                updated_at="2026-04-28T00:00:00+00:00",
                finalized_at=None,
                buckets=(),
            )

    event = {
        "body": (
            '{"style_id":"00000000-0000-0000-0000-000000000001",'
            '"name":"X","date_from":"2026-04-20","date_to":"2026-04-26",'
            '"include_disliked_artists":false,"include_favorites":false}'
        )
    }
    resp = _create_triage_block(event, _Repo(), "u-1", "corr-1")
    assert captured["include_disliked_labels"] is True
    assert captured["include_disliked_artists"] is False
    assert captured["compilations_to_not"] is True
    assert captured["include_favorites"] is False

    import json as _json
    body = _json.loads(resp["body"])
    assert body["include_disliked_labels"] is True
    assert body["include_disliked_artists"] is False
    assert body["compilations_to_not"] is True
    assert body["include_favorites"] is False
```

If the existing test file already constructs `TriageBlockRow` in a fixture, also add the three new fields there to keep it valid.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST tests/unit/test_curation_handler_triage.py -q`
Expected: FAIL — `create_block` not called with `include_disliked_artists` / `body` missing the new keys.

- [ ] **Step 3: Forward the flags in `_create_triage_block`**

Replace the `triage_repo.create_block(...)` call with:

```python
    out = triage_repo.create_block(
        user_id=user_id,
        style_id=schema.style_id,
        name=schema.name,
        date_from=schema.date_from,
        date_to=schema.date_to,
        old_offset_weeks=schema.old_offset_weeks,
        include_disliked_labels=schema.include_disliked_labels,
        include_disliked_artists=schema.include_disliked_artists,
        compilations_to_not=schema.compilations_to_not,
        include_favorites=schema.include_favorites,
    )
```

- [ ] **Step 4: Serialize the flags in `_serialize_triage_block`**

After the `"include_disliked_labels": row.include_disliked_labels,` line add:

```python
        "include_disliked_artists": row.include_disliked_artists,
        "compilations_to_not": row.compilations_to_not,
        "include_favorites": row.include_favorites,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTEST tests/unit/test_curation_handler_triage.py -q`
Expected: PASS.

- [ ] **Step 6: Commit** (via `caveman:caveman-commit`)

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_handler_triage.py
git commit -m "<generated subject>"
```

---

## Task 6: OpenAPI + frontend schema types

**Files:**
- Modify: `scripts/generate_openapi.py:298` (response schema)
- Regenerate: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

- [ ] **Step 1: Add response booleans in `generate_openapi.py`**

In `TRIAGE_BLOCK_DETAIL["properties"]`, replace:

```python
        "include_disliked_labels": {"type": "boolean"},
```

with:

```python
        "include_disliked_labels": {"type": "boolean"},
        "include_disliked_artists": {"type": "boolean"},
        "compilations_to_not": {"type": "boolean"},
        "include_favorites": {"type": "boolean"},
```

(The `CreateTriageBlockIn` request schema is generated from the Pydantic model — the new fields appear automatically. Confirm in step 3.)

- [ ] **Step 2: Regenerate the OpenAPI document**

Run: `PYTHONPATH=src PY scripts/generate_openapi.py`
Expected: exits 0, rewrites `docs/api/openapi.yaml`.

- [ ] **Step 3: Verify both request and response carry the fields**

Run: `grep -n "include_favorites\|compilations_to_not\|include_disliked_artists" docs/api/openapi.yaml`
Expected: matches under both the `CreateTriageBlockIn` request schema and the triage block detail response schema.

- [ ] **Step 4: Regenerate the frontend types**

Run: `cd frontend && pnpm api:types`
Expected: rewrites `src/api/schema.d.ts`; `git diff` shows the new boolean fields.

- [ ] **Step 5: Commit** (via `caveman:caveman-commit`)

```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "<generated subject>"
```

---

## Task 7: Frontend schema + hook input

**Files:**
- Modify: `frontend/src/features/triage/lib/triageSchemas.ts:28-33`
- Modify: `frontend/src/features/triage/hooks/useCreateTriageBlock.ts:27-34`

No standalone test (covered by the dialog test in Task 8). Type-check verifies it.

- [ ] **Step 1: Extend the Zod schema**

Replace `createTriageBlockSchema` with:

```ts
export const createTriageBlockSchema = z.object({
  name: triageNameSchema,
  dateRange: triageDateRangeSchema,
  oldOffsetWeeks: z.number().int().min(0).max(520).default(0),
  includeDislikedLabels: z.boolean().default(true),
  includeDislikedArtists: z.boolean().default(true),
  compilationsToNot: z.boolean().default(true),
  includeFavorites: z.boolean().default(true),
});
```

- [ ] **Step 2: Extend the hook input interface**

In `useCreateTriageBlock.ts`, replace the `CreateTriageBlockInput` interface with:

```ts
export interface CreateTriageBlockInput {
  style_id: string;
  name: string;
  date_from: string;
  date_to: string;
  old_offset_weeks?: number;
  include_disliked_labels?: boolean;
  include_disliked_artists?: boolean;
  compilations_to_not?: boolean;
  include_favorites?: boolean;
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm tsc --noEmit` (or the project's typecheck script if different — check `frontend/package.json` `scripts`).
Expected: no new errors.

- [ ] **Step 4: Commit** (via `caveman:caveman-commit`)

```bash
git add frontend/src/features/triage/lib/triageSchemas.ts frontend/src/features/triage/hooks/useCreateTriageBlock.ts
git commit -m "<generated subject>"
```

---

## Task 8: Dialog — default-on toggles + new Switches

**Files:**
- Modify: `frontend/src/features/triage/components/CreateTriageBlockDialog.tsx`
- Test: `frontend/src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx`

- [ ] **Step 1: Update + add failing tests**

In `CreateTriageBlockDialog.test.tsx`:

(a) In `submits populate options from the advanced section`, **delete** the line:
```ts
    await user.click(screen.getByLabelText(/Send disliked-label tracks to NOT/i));
```
(the switch now defaults ON; clicking it would turn it OFF and break `expect(body.include_disliked_labels).toBe(true)`).

(b) Add a new test asserting all four flags submit ON without opening Advanced:

```ts
  it('submits all classification flags on by default without opening advanced', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    server.use(
      http.post('http://localhost/triage/blocks', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body.include_disliked_labels).toBe(true);
        expect(body.include_disliked_artists).toBe(true);
        expect(body.compilations_to_not).toBe(true);
        expect(body.include_favorites).toBe(true);
        return HttpResponse.json(
          {
            id: 'b1',
            style_id: 's1',
            style_name: 'House',
            name: 'House W17',
            date_from: '2026-04-20',
            date_to: '2026-04-26',
            status: 'IN_PROGRESS',
            created_at: 'now',
            updated_at: 'now',
            finalized_at: null,
            buckets: [],
          },
          { status: 201 },
        );
      }),
    );

    renderDialog({ onClose });
    const dateInput = screen.getByLabelText('Window');
    await user.click(dateInput);
    await user.type(dateInput, '2026-04-20 – 2026-04-26');
    await waitFor(() => {
      expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('House W17');
    });
    await user.click(screen.getByRole('button', { name: /create/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `cd frontend && pnpm test src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx`
Expected: the new test FAILs (`body.include_favorites` is `undefined`).

- [ ] **Step 3: Default the form values ON**

In `CreateTriageBlockDialog.tsx`, replace the `initialValues` object with:

```ts
    initialValues: {
      // Mantine 9 DatePickerInput accepts/emits string|null for range slots.
      // Use null placeholders; Zod coercion handles the string conversion on submit.
      name: '',
      dateRange: [null as unknown as Date, null as unknown as Date],
      oldOffsetWeeks: 0,
      includeDislikedLabels: true,
      includeDislikedArtists: true,
      compilationsToNot: true,
      includeFavorites: true,
    },
```

- [ ] **Step 4: Pass the new flags to the mutation**

In `handleSubmit`, replace the `await create.mutateAsync({...})` payload with:

```ts
      await create.mutateAsync({
        style_id: styleId,
        name: values.name.trim(),
        date_from: dayjs(from).format('YYYY-MM-DD'),
        date_to: dayjs(to).format('YYYY-MM-DD'),
        old_offset_weeks: values.oldOffsetWeeks,
        include_disliked_labels: values.includeDislikedLabels,
        include_disliked_artists: values.includeDislikedArtists,
        compilations_to_not: values.compilationsToNot,
        include_favorites: values.includeFavorites,
      });
```

- [ ] **Step 5: Add the three Switches inside the Advanced Collapse**

In the `<Collapse expanded={advancedOpen}>` `<Stack>`, after the existing disliked-labels `<Switch>` add:

```tsx
            <Switch
              label={t('triage.form.include_disliked_artists_label')}
              description={t('triage.form.include_disliked_artists_description')}
              {...form.getInputProps('includeDislikedArtists', { type: 'checkbox' })}
            />
            <Switch
              label={t('triage.form.compilations_to_not_label')}
              description={t('triage.form.compilations_to_not_description')}
              {...form.getInputProps('compilationsToNot', { type: 'checkbox' })}
            />
            <Switch
              label={t('triage.form.include_favorites_label')}
              description={t('triage.form.include_favorites_description')}
              {...form.getInputProps('includeFavorites', { type: 'checkbox' })}
            />
```

- [ ] **Step 6: Add i18n strings**

In `frontend/src/i18n/en.json`, under `triage.form`, after `include_disliked_labels_description` add:

```json
    "include_disliked_artists_label": "Send disliked-artist tracks to NOT",
    "include_disliked_artists_description": "Tracks by artists you disliked are placed in NOT, regardless of release date.",
    "compilations_to_not_label": "Send compilation tracks to NOT",
    "compilations_to_not_description": "Tracks released on compilations are placed in NOT. Turn off to sort them by release date like any other track.",
    "include_favorites_label": "Collect liked label/artist tracks into FAV",
    "include_favorites_description": "Tracks from labels or artists you liked are collected into the FAV bucket. Likes take priority over dislikes.",
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && pnpm test src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx`
Expected: PASS (updated + new test).

- [ ] **Step 8: Commit** (via `caveman:caveman-commit`)

```bash
git add frontend/src/features/triage/components/CreateTriageBlockDialog.tsx frontend/src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx frontend/src/i18n/en.json
git commit -m "<generated subject>"
```

---

## Task 9: FAV bucket recognised on the frontend

**Files:**
- Modify: `frontend/src/features/triage/lib/bucketLabels.ts:3,15-21`
- Test: `frontend/src/features/triage/lib/__tests__/bucketLabels.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `bucketLabels.test.ts`:

```ts
  it('treats FAV as a technical bucket and labels it FAV', () => {
    const fav = {
      id: 'b-fav',
      bucket_type: 'FAV' as const,
      category_id: null,
      category_name: null,
      inactive: false,
      track_count: 0,
    };
    expect(isTechnical(fav)).toBe(true);
    expect(bucketLabel(fav, ((k: string) => k) as unknown as TFunction)).toBe('FAV');
  });
```

Ensure `isTechnical`, `bucketLabel`, and `TFunction` are imported in the test file (mirror the existing imports there; `TFunction` comes from `i18next`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test src/features/triage/lib/__tests__/bucketLabels.test.ts`
Expected: FAIL — `isTechnical(fav)` is `false` (FAV not in the set) and/or TS error on the `'FAV'` literal.

- [ ] **Step 3: Add FAV to the type and the technical set**

In `bucketLabels.ts`, change:

```ts
export type TechnicalBucketType = 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED' | 'FAV';
```

and:

```ts
const TECHNICAL_TYPES: ReadonlySet<BucketType> = new Set([
  'NEW',
  'OLD',
  'NOT',
  'DISCARD',
  'UNCLASSIFIED',
  'FAV',
]);
```

(`bucketLabel` already returns `bucket.bucket_type` for any non-STAGING type, so `FAV` renders as `FAV` with no further change.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test src/features/triage/lib/__tests__/bucketLabels.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit** (via `caveman:caveman-commit`)

```bash
git add frontend/src/features/triage/lib/bucketLabels.ts frontend/src/features/triage/lib/__tests__/bucketLabels.test.ts
git commit -m "<generated subject>"
```

---

## Task 10: Integration — end-to-end classification

**Files:**
- Test: `tests/integration/test_triage_handler.py`

This proves a real create-block run lands liked tracks in FAV and disliked tracks in NOT, with FAV first in the bucket order. Use the file's existing fixtures (DB seed + handler invocation). If the suite seeds tracks/labels/artists and user prefs, extend a creation test; otherwise add one mirroring the existing create test.

- [ ] **Step 1: Write the failing integration test**

Add a test that seeds: a style, one track on a **liked** label, one track by a **disliked** artist, one plain recent track, and `clouder_user_label_prefs` / `clouder_user_artist_prefs` rows; then POSTs `/triage/blocks` with defaults and asserts:

```python
    # buckets come back FAV-first
    types = [b["bucket_type"] for b in body["buckets"] if b["bucket_type"] != "STAGING"]
    assert types[0] == "FAV"
    # the liked-label track is in FAV, the disliked-artist track is in NOT
    fav = next(b for b in body["buckets"] if b["bucket_type"] == "FAV")
    not_b = next(b for b in body["buckets"] if b["bucket_type"] == "NOT")
    assert fav["track_count"] == 1
    assert not_b["track_count"] == 1
```

Follow the existing test's exact seeding/POST helpers (do not invent new ones). If the integration suite is gated on a live Data API / Postgres and skipped in this environment, mark the test with the same skip marker the other integration tests in this file use.

- [ ] **Step 2: Run it**

Run: `PYTEST tests/integration/test_triage_handler.py -q`
Expected: PASS, or SKIPPED with the same marker as sibling tests if no DB is wired locally.

- [ ] **Step 3: Commit** (via `caveman:caveman-commit`)

```bash
git add tests/integration/test_triage_handler.py
git commit -m "<generated subject>"
```

---

## Task 11: Full verification

- [ ] **Step 1: Backend suite**

Run: `PYTEST -q`
Expected: all pass (or pre-existing skips only).

- [ ] **Step 2: Frontend suite + typecheck + lint**

```bash
cd frontend
pnpm test
pnpm tsc --noEmit
pnpm lint
```
Expected: all green. (`pnpm test:browser` is not required — no CSS/layout change here.)

- [ ] **Step 3: Confirm OpenAPI is in sync**

Run: `PYTHONPATH=src PY scripts/generate_openapi.py && git diff --exit-code docs/api/openapi.yaml frontend/src/api/schema.d.ts`
Expected: exit 0 (no drift since Task 6).

- [ ] **Step 4: Final review**

Use `superpowers:requesting-code-review` or open a PR (PR title/body via `caveman:caveman-commit`).

---

## Self-Review

**Spec coverage:**
- Disliked-label default ON → Task 2 (schema default `True`) + Task 8 (form default).
- Compilation→NOT toggle (default ON, off = sort by date) → Task 4 (gated `compilation_when`) + Task 1 (`compilation_to_not` in pure helper) + Task 8 (Switch).
- Disliked-artist→NOT (default ON) → Task 4 (artist EXISTS in disliked terms) + Task 8.
- FAV bucket (liked label/artist, default ON, technical, FAV-first, not promoted) → Task 1 (constant + display order) + Task 3 (CHECK) + Task 4 (FAV branch + ordering CASE) + Task 9 (frontend type). Not-promoted-at-finalize needs no change (finalize only promotes STAGING).
- Persist flags as columns → Task 3 (columns) + Task 4 (INSERT + dataclass + fetch) + Task 5 (serialize) + Task 6 (response schema).
- Likes beat dislikes → Task 1 + Task 4 (branch 1 before branch 2).

**Placeholder scan:** the only non-literal steps are Task 10 (integration test must reuse existing seed helpers) and the `pnpm tsc/lint` script names — both flagged to confirm against `frontend/package.json`. No "TBD"/"handle edge cases" left.

**Type consistency:** field names are identical across layers — Python `include_disliked_artists` / `compilations_to_not` / `include_favorites`; TS camelCase form fields `includeDislikedArtists` / `compilationsToNot` / `includeFavorites` mapping to snake_case payload keys; bucket type literal `'FAV'`. `classify_bucket_type` params (`is_favorite`, `is_disliked`, `compilation_to_not`) match Task 1's signature and its tests.
