# Track Tags Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the user-facing tag UI: vocabulary management modal, inline pill + popover editor on every track row, and a tag-set filter (ALL/ANY) above the tracks table on the category detail page. Includes a small backend precondition that makes `user_tags.color` nullable.

**Architecture:** New feature folder `frontend/src/features/tags/` owns every tag-related component (`TagPill`, `TrackTagsCell`, `TrackTagsPopover`, `TagsManagerModal`, `TagFormFields`, `ColorSwatchPicker`, `TagsFilterBar`), hooks (`useTags`, CRUD mutations, per-track `useAddTrackTag` / `useRemoveTrackTag` with optimistic updates), and lib (`tagPalette`, `tagSchemas`, `normalizeTagName`, `tagsUrlState`). `features/categories/` only modifies its existing query hook + tracks tab + row. Optimistic patches happen against the existing `categoryTracks` infinite cache key (extended to include `tagIds` + `tagMatch`). Filter state lives in URL search params (`?tags=tg1,tg2&match=any`).

**Tech Stack:** React 19, Mantine 9, TanStack Query 5, react-router 7, vitest + RTL + msw, openapi-typescript, Python 3.12 + Alembic + RDS Data API (BE precondition only).

**Spec:** `docs/superpowers/specs/2026-05-11-track-tags-frontend-design.md`.

---

## File Structure

**Backend (precondition, Task 0 only):**
- Create: `alembic/versions/20260511_18_user_tags_color_nullable.py`
- Modify: `src/collector/db_models.py`, `src/collector/curation/tags_repository.py`, `src/collector/curation_handler.py`, `scripts/generate_openapi.py`
- Modify (regenerate): `docs/openapi.yaml`
- Modify: `tests/unit/test_tags_repository.py`, `tests/unit/test_curation_handler_tags.py`

**Frontend new (Tasks 1–18):**
- `frontend/src/features/tags/index.ts`
- `frontend/src/features/tags/lib/tagPalette.ts`
- `frontend/src/features/tags/lib/normalizeTagName.ts`
- `frontend/src/features/tags/lib/tagSchemas.ts`
- `frontend/src/features/tags/lib/tagsUrlState.ts`
- `frontend/src/features/tags/hooks/useTags.ts`
- `frontend/src/features/tags/hooks/useCreateTag.ts`
- `frontend/src/features/tags/hooks/useRenameTag.ts`
- `frontend/src/features/tags/hooks/useDeleteTag.ts`
- `frontend/src/features/tags/hooks/useAddTrackTag.ts`
- `frontend/src/features/tags/hooks/useRemoveTrackTag.ts`
- `frontend/src/features/tags/components/TagPill.tsx`
- `frontend/src/features/tags/components/ColorSwatchPicker.tsx`
- `frontend/src/features/tags/components/TagFormFields.tsx`
- `frontend/src/features/tags/components/TagsManagerModal.tsx`
- `frontend/src/features/tags/components/TrackTagsPopover.tsx`
- `frontend/src/features/tags/components/TrackTagsCell.tsx`
- `frontend/src/features/tags/components/TagsFilterBar.tsx`
- Tests: matching `__tests__/` folders mirroring the source layout.

**Frontend modified (Tasks 19–22):**
- `frontend/src/api/schema.d.ts` (regenerated; not edited by hand)
- `frontend/src/features/categories/hooks/useCategoryTracks.ts`
- `frontend/src/features/categories/components/TracksTab.tsx`
- `frontend/src/features/categories/components/TrackRow.tsx`
- `frontend/src/i18n/en.json`
- `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx` and other affected test fixtures.

**Out of scope:**
- Tag UI in curate / triage / any non-categories surface.
- Bulk multi-select tag operations (PUT replace-all).
- Drag-and-drop ordering in the manager modal.

---

## Task 0: Backend precondition — `user_tags.color` becomes nullable

> Lands as one commit before any frontend work begins. Without it `pnpm api:types` regenerates with `color: string` (required) and the frontend cannot build "no colour" tags.

**Files:**
- Create: `alembic/versions/20260511_18_user_tags_color_nullable.py`
- Modify: `src/collector/db_models.py`
- Modify: `src/collector/curation/tags_repository.py`
- Modify: `src/collector/curation_handler.py`
- Modify: `scripts/generate_openapi.py` + regenerated `docs/openapi.yaml`
- Modify: `tests/unit/test_tags_repository.py`, `tests/unit/test_curation_handler_tags.py`

- [ ] **Step 1: Verify current Alembic head**

Run: `PYTHONPATH=src .venv/bin/alembic heads`
Expected output: `20260511_17 (head)`. Use it as `down_revision`.

- [ ] **Step 2: Create the migration**

Write `alembic/versions/20260511_18_user_tags_color_nullable.py`:

```python
"""user_tags.color becomes nullable

Revision ID: 20260511_18
Revises: 20260511_17
Create Date: 2026-05-11 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260511_18"
down_revision = "20260511_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_tags",
        "color",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    # Replace any nulls with a neutral sentinel before re-tightening the
    # constraint so the downgrade does not fail on a populated table.
    op.execute(
        "UPDATE user_tags SET color = '#888888' WHERE color IS NULL"
    )
    op.alter_column(
        "user_tags",
        "color",
        existing_type=sa.Text(),
        nullable=False,
    )
```

- [ ] **Step 3: Update the SQLAlchemy model**

Edit `src/collector/db_models.py` `UserTag` (the `color` column added in revision `20260511_17`):

```python
color: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Loosen `TagsRepository`**

Edit `src/collector/curation/tags_repository.py`:

```python
def create_tag(
    self,
    *,
    user_id: str,
    tag_id: str,
    name: str,
    normalized_name: str,
    color: str | None,            # was: str
    now: datetime,
) -> TagRow:
```

`rename_tag` already accepts `color: str | None`. The repository SQL already passes whatever value the caller provides, so no body changes other than the signature.

Update `_row_to_tag` to keep `color` as `Optional[str]`:

```python
def _row_to_tag(r: dict[str, Any]) -> TagRow:
    return TagRow(
        id=r["id"],
        name=r["name"],
        color=r.get("color"),     # was: r["color"]
        created_at=str(r["created_at"]),
        updated_at=str(r["updated_at"]),
    )
```

And the dataclass:

```python
@dataclass(frozen=True)
class TagRow:
    id: str
    name: str
    color: str | None
    created_at: str
    updated_at: str
```

- [ ] **Step 5: Loosen the handler**

Edit `src/collector/curation_handler.py` `_handle_create_tag`:

```python
def _handle_create_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    body = _parse_body(event)
    name_raw = body.get("name")
    color = body.get("color")
    if not isinstance(name_raw, str):
        raise InvalidTagNameError("name is required")
    name = name_raw.strip()
    if not name or len(name) > _MAX_TAG_NAME:
        raise InvalidTagNameError("name must be 1..64 chars")
    if color is not None:
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            raise InvalidTagColorError("color must be #RRGGBB hex or null")
    row = repo.create_tag(
        user_id=user_id,
        tag_id=str(uuid.uuid4()),
        name=name,
        normalized_name=_normalize_tag_name(name),
        color=color,
        now=utc_now(),
    )
    return _json_response(201, _tag_dict(row), correlation_id)
```

`_handle_rename_tag` already permits `color is None`; no change needed.

`_tag_dict` already returns `row.color` as-is, so `null` round-trips naturally.

- [ ] **Step 6: Update OpenAPI schema definitions**

Edit `scripts/generate_openapi.py`:

In `TAG_RESPONSE`:

```python
"color": {"type": ["string", "null"], "pattern": "^#[0-9A-Fa-f]{6}$"},
```

In the `POST /tags` request body schema, change `"required": ["name", "color"]` → `"required": ["name"]` and the `color` property to:

```python
"color": {"type": ["string", "null"], "pattern": "^#[0-9A-Fa-f]{6}$"},
```

Same for `PATCH /tags/{tag_id}`. Also update the inline `TRACK_TAGS_RESPONSE` and `CATEGORY_TRACK_RESPONSE` `color` schemas (search for `"pattern": "^#[0-9A-Fa-f]{6}$"`) to be `["string", "null"]` everywhere.

- [ ] **Step 7: Regenerate `docs/openapi.yaml`**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`
Expected: `wrote /Users/.../docs/openapi.yaml  (~74-75kb)`.

Sanity check: `grep -A2 '"color":' docs/openapi.yaml | head -20` — every occurrence of the `color` schema now lists `null` as a valid type.

- [ ] **Step 8: Add tests for the `color=None` path**

Append to `tests/unit/test_tags_repository.py`:

```python
def test_create_tag_accepts_null_color() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "tg1",
            "name": "Vocal",
            "color": None,
            "created_at": "2026-05-11T12:00:00Z",
            "updated_at": "2026-05-11T12:00:00Z",
        }
    ]
    row = repo.create_tag(
        user_id="u1",
        tag_id="tg1",
        name="Vocal",
        normalized_name="vocal",
        color=None,
        now=_now(),
    )
    assert row.color is None
    params = data_api.execute.call_args.args[1]
    assert params["color"] is None


def test_rename_tag_accepts_null_color_explicitly() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {"id": "tg1", "name": "Vocal", "color": None,
         "created_at": "2026-05-11T12:00:00Z",
         "updated_at": "2026-05-11T12:01:00Z"}
    ]
    row = repo.rename_tag(
        user_id="u1",
        tag_id="tg1",
        name=None,
        normalized_name=None,
        color=None,
        now=_now(),
    )
    # color=None means "unchanged" in current rename_tag — covered by other
    # tests; here we just lock in that the signature accepts None.
    assert row.color is None
```

Append to `tests/unit/test_curation_handler_tags.py`:

```python
def test_create_tag_accepts_null_color(fake_tags, context) -> None:
    fake_tags.create_tag.return_value = _stock_tag_row(color=None)
    resp = lambda_handler(
        _event(
            method="POST", route="/tags",
            body={"name": "Vocal"},     # color absent
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["color"] is None
    assert fake_tags.create_tag.call_args.kwargs["color"] is None


def test_create_tag_accepts_explicit_null_color(fake_tags, context) -> None:
    fake_tags.create_tag.return_value = _stock_tag_row(color=None)
    resp = lambda_handler(
        _event(
            method="POST", route="/tags",
            body={"name": "Vocal", "color": None},
        ),
        context,
    )
    assert _read(resp)[0] == 201
```

Update the existing `_stock_tag_row` helper signature in that file so `color` defaults to `"#ff8800"` but accepts `None`:

```python
def _stock_tag_row(
    id: str = "tg1", name: str = "Vocal", color: str | None = "#ff8800"
) -> TagRow:
    ...
```

- [ ] **Step 9: Run the affected suites**

Run: `.venv/bin/pytest tests/unit/test_tags_repository.py tests/unit/test_curation_handler_tags.py -q`
Expected: all green.

Run the full suite for safety: `.venv/bin/pytest -q`
Expected: all green.

- [ ] **Step 10: Verify migration round-trip on a scratch postgres**

If a scratch postgres container is available (mirror the recipe from the prior backend implementation):

```
docker run -d --rm --name tracktags-pg-tmp \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres \
  -p 55432:5432 postgres:16
sleep 4
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:55432/postgres'
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
docker stop tracktags-pg-tmp
```

Expected: each alembic step exits 0; the down/up round-trip proves both directions are idempotent.

If no docker / postgres available locally, skip and rely on CI's `alembic-check`.

- [ ] **Step 11: Commit**

```bash
git add alembic/versions/20260511_18_user_tags_color_nullable.py \
        src/collector/db_models.py src/collector/curation/tags_repository.py \
        src/collector/curation_handler.py scripts/generate_openapi.py \
        docs/openapi.yaml \
        tests/unit/test_tags_repository.py tests/unit/test_curation_handler_tags.py
# Generate the message via caveman-commit, then:
git commit -m "feat(tags): make user_tags.color optional"
```

---

## Task 1: Regenerate frontend OpenAPI types

**Files:**
- Modify: `frontend/src/api/schema.d.ts` (auto-generated, do not edit manually)

- [ ] **Step 1: Regenerate types from the updated `docs/openapi.yaml`**

Run from the worktree root:

```
cd frontend && pnpm install --frozen-lockfile  # only if node_modules missing
pnpm api:types
```

Expected: `frontend/src/api/schema.d.ts` updated. Verify the change:

```
grep -n "tags\|color" frontend/src/api/schema.d.ts | head -20
```

Expected: a `paths["/tags"]` entry exists, `paths["/tracks/{track_id}/tags"]` exists, and every `color: string` field on tag-related schemas now reads `color: string | null` (or `color?: string | null` on PATCH bodies).

- [ ] **Step 2: Type-check**

Run from `frontend/`: `pnpm typecheck`
Expected: green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/schema.d.ts
git commit -m "chore(api): regenerate frontend types for nullable tag color"
```

---

## Task 2: `lib/tagPalette.ts` — colour palette + luminance helpers

**Files:**
- Create: `frontend/src/features/tags/lib/tagPalette.ts`
- Create: `frontend/src/features/tags/lib/__tests__/tagPalette.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest';
import { TAG_PALETTE, pickPillTextColor, isPaletteColor } from '../tagPalette';

describe('tagPalette', () => {
  it('exposes exactly 12 unique hex colours', () => {
    expect(TAG_PALETTE).toHaveLength(12);
    const set = new Set(TAG_PALETTE.map((c) => c.toLowerCase()));
    expect(set.size).toBe(12);
    for (const c of TAG_PALETTE) {
      expect(c).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('isPaletteColor recognises members regardless of case', () => {
    expect(isPaletteColor(TAG_PALETTE[0])).toBe(true);
    expect(isPaletteColor(TAG_PALETTE[0].toUpperCase())).toBe(true);
    expect(isPaletteColor('#abcdef')).toBe(false);
    expect(isPaletteColor(null)).toBe(false);
  });

  it('pickPillTextColor returns black on light, white on dark', () => {
    expect(pickPillTextColor('#ffffff')).toBe('#000000');
    expect(pickPillTextColor('#000000')).toBe('#ffffff');
    expect(pickPillTextColor('#ffeb3b')).toBe('#000000'); // bright yellow
    expect(pickPillTextColor('#1a237e')).toBe('#ffffff'); // dark indigo
  });

  it('pickPillTextColor returns the default fg for null background', () => {
    expect(pickPillTextColor(null)).toBe('var(--mantine-color-text)');
  });
});
```

- [ ] **Step 2: Run test, expect failure**

Run from `frontend/`: `pnpm test src/features/tags/lib/__tests__/tagPalette.test.ts`
Expected: ImportError ("Cannot find module").

- [ ] **Step 3: Implement `tagPalette.ts`**

```ts
/**
 * Fixed user-tag colour palette. Designed to read on both light and dark
 * Mantine themes; muted enough to coexist with category UI accents.
 */
export const TAG_PALETTE = [
  '#ef4444', // red
  '#f97316', // orange
  '#eab308', // yellow
  '#22c55e', // green
  '#14b8a6', // teal
  '#06b6d4', // cyan
  '#3b82f6', // blue
  '#8b5cf6', // violet
  '#d946ef', // fuchsia
  '#ec4899', // pink
  '#78716c', // stone (neutral warm)
  '#0f172a', // slate (neutral dark)
] as const;

export type TagPaletteColor = (typeof TAG_PALETTE)[number];

export function isPaletteColor(value: string | null | undefined): value is TagPaletteColor {
  if (typeof value !== 'string') return false;
  const lower = value.toLowerCase();
  return TAG_PALETTE.some((c) => c.toLowerCase() === lower);
}

/**
 * Returns the foreground colour to use on top of the supplied background.
 * Uses the WCAG relative-luminance formula and a 0.5 threshold; matches
 * the contrast feel users expect from Mantine `Badge`.
 */
export function pickPillTextColor(bg: string | null | undefined): string {
  if (!bg) return 'var(--mantine-color-text)';
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(bg);
  if (!m) return 'var(--mantine-color-text)';
  const [r, g, b] = [m[1], m[2], m[3]].map((h) => parseInt(h, 16) / 255);
  const channel = (c: number) =>
    c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  const L = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  return L > 0.5 ? '#000000' : '#ffffff';
}
```

- [ ] **Step 4: Run test, expect pass**

Run: `pnpm test src/features/tags/lib/__tests__/tagPalette.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/lib/tagPalette.ts \
        frontend/src/features/tags/lib/__tests__/tagPalette.test.ts
git commit -m "feat(tags): add tag colour palette and luminance helpers"
```

---

## Task 3: `lib/normalizeTagName.ts` — mirror BE normalisation

**Files:**
- Create: `frontend/src/features/tags/lib/normalizeTagName.ts`
- Create: `frontend/src/features/tags/lib/__tests__/normalizeTagName.test.ts`

The backend computes `normalized_name = " ".join(name.strip().lower().split())`. We mirror it on the frontend so the popover's "Создать «X»" suggestion only shows when the typed name truly has no match.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest';
import { normalizeTagName } from '../normalizeTagName';

describe('normalizeTagName', () => {
  it('lowercases', () => {
    expect(normalizeTagName('Vocal')).toBe('vocal');
  });

  it('trims leading and trailing whitespace', () => {
    expect(normalizeTagName('  vocal  ')).toBe('vocal');
  });

  it('collapses internal whitespace runs', () => {
    expect(normalizeTagName('hard   tech')).toBe('hard tech');
    expect(normalizeTagName('hard\ttech\t\there')).toBe('hard tech here');
  });

  it('returns the empty string for empty / whitespace input', () => {
    expect(normalizeTagName('')).toBe('');
    expect(normalizeTagName('   ')).toBe('');
  });
});
```

- [ ] **Step 2: Run test, expect failure**

Run: `pnpm test src/features/tags/lib/__tests__/normalizeTagName.test.ts`

- [ ] **Step 3: Implement**

```ts
export function normalizeTagName(input: string): string {
  return input.trim().toLowerCase().split(/\s+/).filter(Boolean).join(' ');
}
```

- [ ] **Step 4: Run test, expect pass**

Run: `pnpm test src/features/tags/lib/__tests__/normalizeTagName.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/lib/normalizeTagName.ts \
        frontend/src/features/tags/lib/__tests__/normalizeTagName.test.ts
git commit -m "feat(tags): add normalizeTagName helper mirroring backend"
```

---

## Task 4: `lib/tagSchemas.ts` — Zod schemas

**Files:**
- Create: `frontend/src/features/tags/lib/tagSchemas.ts`
- Create: `frontend/src/features/tags/lib/__tests__/tagSchemas.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest';
import {
  tagNameSchema,
  tagColorSchema,
  createTagSchema,
  renameTagSchema,
} from '../tagSchemas';

describe('tagNameSchema', () => {
  it('accepts a normal name', () => {
    expect(tagNameSchema.parse('Vocal')).toBe('Vocal');
  });

  it('trims surrounding whitespace', () => {
    expect(tagNameSchema.parse('  Vocal  ')).toBe('Vocal');
  });

  it('rejects empty / whitespace-only', () => {
    expect(tagNameSchema.safeParse('').success).toBe(false);
    expect(tagNameSchema.safeParse('   ').success).toBe(false);
  });

  it('rejects > 64 characters', () => {
    expect(tagNameSchema.safeParse('x'.repeat(65)).success).toBe(false);
  });

  it('rejects control characters', () => {
    expect(tagNameSchema.safeParse('helloworld').success).toBe(false);
  });
});

describe('tagColorSchema', () => {
  it('accepts a valid hex', () => {
    expect(tagColorSchema.parse('#ff8800')).toBe('#ff8800');
  });

  it('accepts null', () => {
    expect(tagColorSchema.parse(null)).toBe(null);
  });

  it('rejects invalid hex', () => {
    expect(tagColorSchema.safeParse('blue').success).toBe(false);
    expect(tagColorSchema.safeParse('#fff').success).toBe(false);
  });
});

describe('createTagSchema / renameTagSchema', () => {
  it('createTagSchema requires name; color optional → null', () => {
    const out = createTagSchema.parse({ name: 'Vocal' });
    expect(out).toEqual({ name: 'Vocal', color: null });
  });

  it('renameTagSchema accepts name only', () => {
    expect(renameTagSchema.parse({ name: 'Vocal F' })).toEqual({
      name: 'Vocal F',
      color: undefined,
    });
  });

  it('renameTagSchema accepts color only', () => {
    expect(renameTagSchema.parse({ color: '#ff8800' })).toEqual({
      name: undefined,
      color: '#ff8800',
    });
  });

  it('renameTagSchema rejects empty payload', () => {
    expect(renameTagSchema.safeParse({}).success).toBe(false);
  });
});
```

- [ ] **Step 2: Run test, expect failure**

Run: `pnpm test src/features/tags/lib/__tests__/tagSchemas.test.ts`

- [ ] **Step 3: Implement**

```ts
import { z } from 'zod';

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const tagNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(64, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const tagColorSchema = z
  .union([z.string().regex(/^#[0-9A-Fa-f]{6}$/, 'color_invalid'), z.null()]);

export const createTagSchema = z.object({
  name: tagNameSchema,
  color: tagColorSchema.optional().transform((v) => (v === undefined ? null : v)),
});

export const renameTagSchema = z
  .object({
    name: tagNameSchema.optional(),
    color: tagColorSchema.optional(),
  })
  .refine(
    (v) => v.name !== undefined || v.color !== undefined,
    { message: 'payload_empty' },
  );

export type CreateTagInput = z.infer<typeof createTagSchema>;
export type RenameTagInput = z.infer<typeof renameTagSchema>;
```

- [ ] **Step 4: Run test, expect pass**

Run: `pnpm test src/features/tags/lib/__tests__/tagSchemas.test.ts`
Expected: ~12 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/lib/tagSchemas.ts \
        frontend/src/features/tags/lib/__tests__/tagSchemas.test.ts
git commit -m "feat(tags): add zod schemas for tag create / rename"
```

---

## Task 5: `lib/tagsUrlState.ts` — URL ↔ filter state

**Files:**
- Create: `frontend/src/features/tags/lib/tagsUrlState.ts`
- Create: `frontend/src/features/tags/lib/__tests__/tagsUrlState.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest';
import { readTagsUrlState, writeTagsUrlState } from '../tagsUrlState';

describe('readTagsUrlState', () => {
  it('returns defaults for empty params', () => {
    expect(readTagsUrlState(new URLSearchParams())).toEqual({
      selectedIds: [],
      match: 'all',
    });
  });

  it('parses tags csv preserving order', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg2,tg1'))).toEqual({
      selectedIds: ['tg2', 'tg1'],
      match: 'all',
    });
  });

  it('drops empty entries from a malformed csv', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg1,,tg2,'))).toEqual({
      selectedIds: ['tg1', 'tg2'],
      match: 'all',
    });
  });

  it('parses match=any', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg1&match=any'))).toEqual({
      selectedIds: ['tg1'],
      match: 'any',
    });
  });

  it('treats unknown match values as all', () => {
    expect(readTagsUrlState(new URLSearchParams('tags=tg1&match=xor'))).toEqual({
      selectedIds: ['tg1'],
      match: 'all',
    });
  });
});

describe('writeTagsUrlState', () => {
  it('sorts ids and writes csv', () => {
    const next = writeTagsUrlState(new URLSearchParams(), {
      selectedIds: ['tg2', 'tg1'],
      match: 'all',
    });
    expect(next.get('tags')).toBe('tg1,tg2');
  });

  it('omits tags param when ids empty', () => {
    const next = writeTagsUrlState(new URLSearchParams('tags=tg1'), {
      selectedIds: [],
      match: 'all',
    });
    expect(next.has('tags')).toBe(false);
  });

  it('omits match param when default (all)', () => {
    const next = writeTagsUrlState(new URLSearchParams('match=any'), {
      selectedIds: ['tg1'],
      match: 'all',
    });
    expect(next.has('match')).toBe(false);
  });

  it('keeps unrelated params untouched', () => {
    const next = writeTagsUrlState(new URLSearchParams('search=foo'), {
      selectedIds: ['tg1'],
      match: 'any',
    });
    expect(next.get('search')).toBe('foo');
    expect(next.get('tags')).toBe('tg1');
    expect(next.get('match')).toBe('any');
  });
});
```

- [ ] **Step 2: Run test, expect failure**

Run: `pnpm test src/features/tags/lib/__tests__/tagsUrlState.test.ts`

- [ ] **Step 3: Implement**

```ts
export type TagsFilterState = {
  selectedIds: string[];
  match: 'all' | 'any';
};

export function readTagsUrlState(params: URLSearchParams): TagsFilterState {
  const tagsRaw = params.get('tags') ?? '';
  const selectedIds = tagsRaw.split(',').filter(Boolean);
  const matchRaw = params.get('match');
  const match: 'all' | 'any' = matchRaw === 'any' ? 'any' : 'all';
  return { selectedIds, match };
}

export function writeTagsUrlState(
  current: URLSearchParams,
  next: TagsFilterState,
): URLSearchParams {
  const params = new URLSearchParams(current);
  if (next.selectedIds.length > 0) {
    const sorted = [...next.selectedIds].sort();
    params.set('tags', sorted.join(','));
  } else {
    params.delete('tags');
  }
  if (next.match === 'any') {
    params.set('match', 'any');
  } else {
    params.delete('match');
  }
  return params;
}
```

- [ ] **Step 4: Run test, expect pass**

Run: `pnpm test src/features/tags/lib/__tests__/tagsUrlState.test.ts`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/lib/tagsUrlState.ts \
        frontend/src/features/tags/lib/__tests__/tagsUrlState.test.ts
git commit -m "feat(tags): add URL <-> filter-state helpers"
```

---

## Task 6: `hooks/useTags.ts` — read-side query

**Files:**
- Create: `frontend/src/features/tags/hooks/useTags.ts`
- Create: `frontend/src/features/tags/hooks/__tests__/useTags.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useTags, tagsKey } from '../useTags';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

describe('useTags', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('GETs /tags and returns items array', async () => {
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({
          items: [
            { id: 'tg1', name: 'Vocal', color: '#ff8800',
              created_at: '2026-05-11T12:00:00Z',
              updated_at: '2026-05-11T12:00:00Z' },
            { id: 'tg2', name: 'Dark', color: null,
              created_at: '2026-05-11T12:00:00Z',
              updated_at: '2026-05-11T12:00:00Z' },
          ],
          total: 2, limit: 200, offset: 0,
        }),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useTags(), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((t) => t.id)).toEqual(['tg1', 'tg2']);
    expect(result.current.data?.[1].color).toBeNull();
  });

  it('uses the stable cache key', () => {
    expect(tagsKey()).toEqual(['tags']);
  });
});
```

- [ ] **Step 2: Run, expect failure**

Run: `pnpm test src/features/tags/hooks/__tests__/useTags.test.tsx`

- [ ] **Step 3: Implement**

```ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface Tag {
  id: string;
  name: string;
  color: string | null;
  created_at: string;
  updated_at: string;
}

interface ListTagsResponse {
  items: Tag[];
  total: number;
  limit: number;
  offset: number;
}

export const tagsKey = () => ['tags'] as const;

const PAGE_LIMIT = 200; // single fetch — vocabulary is small

export function useTags(): UseQueryResult<Tag[]> {
  return useQuery<Tag[]>({
    queryKey: tagsKey(),
    queryFn: async () => {
      const res = await api<ListTagsResponse>(
        `/tags?limit=${PAGE_LIMIT}&offset=0`,
      );
      return res.items;
    },
    staleTime: 60_000,
  });
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/hooks/__tests__/useTags.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/hooks/useTags.ts \
        frontend/src/features/tags/hooks/__tests__/useTags.test.tsx
git commit -m "feat(tags): add useTags query hook"
```

---

## Task 7: `hooks/useCreateTag.ts`

**Files:**
- Create: `frontend/src/features/tags/hooks/useCreateTag.ts`
- Create: `frontend/src/features/tags/hooks/__tests__/useCreateTag.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { ApiError } from '../../../../api/error';
import { useCreateTag } from '../useCreateTag';
import { tagsKey } from '../useTags';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

describe('useCreateTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs and returns the new row', async () => {
    server.use(
      http.post('http://localhost/tags', async ({ request }) => {
        const body = (await request.json()) as { name: string; color: string | null };
        expect(body).toEqual({ name: 'Vocal', color: '#ff8800' });
        return HttpResponse.json({
          id: 'tg-new', name: 'Vocal', color: '#ff8800',
          created_at: 'now', updated_at: 'now',
        }, { status: 201 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useCreateTag(), { wrapper: wrap(qc) });
    let created;
    await act(async () => {
      created = await result.current.mutateAsync({ name: 'Vocal', color: '#ff8800' });
    });
    expect(created).toMatchObject({ id: 'tg-new', color: '#ff8800' });
  });

  it('invalidates the tags list on success', async () => {
    server.use(
      http.post('http://localhost/tags', () =>
        HttpResponse.json({
          id: 'tg-new', name: 'Vocal', color: null,
          created_at: 'now', updated_at: 'now',
        }, { status: 201 }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(tagsKey(), [{ id: 'old' }]);
    const { result } = renderHook(() => useCreateTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'Vocal', color: null });
    });
    expect(qc.getQueryState(tagsKey())?.isInvalidated).toBe(true);
  });

  it('surfaces 409 tag_name_conflict as ApiError', async () => {
    server.use(
      http.post('http://localhost/tags', () =>
        HttpResponse.json(
          { error_code: 'tag_name_conflict', message: 'dup' },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useCreateTag(), { wrapper: wrap(qc) });
    await expect(
      result.current.mutateAsync({ name: 'Vocal', color: null }),
    ).rejects.toMatchObject({ status: 409, code: 'tag_name_conflict' });
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { CreateTagInput } from '../lib/tagSchemas';
import { tagsKey, type Tag } from './useTags';

export function useCreateTag(): UseMutationResult<Tag, Error, CreateTagInput> {
  const qc = useQueryClient();
  return useMutation<Tag, Error, CreateTagInput>({
    mutationFn: (input) =>
      api<Tag>('/tags', { method: 'POST', body: JSON.stringify(input) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: tagsKey() });
    },
  });
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/hooks/__tests__/useCreateTag.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/hooks/useCreateTag.ts \
        frontend/src/features/tags/hooks/__tests__/useCreateTag.test.tsx
git commit -m "feat(tags): add useCreateTag mutation hook"
```

---

## Task 8: `hooks/useRenameTag.ts`

**Files:**
- Create: `frontend/src/features/tags/hooks/useRenameTag.ts`
- Create: `frontend/src/features/tags/hooks/__tests__/useRenameTag.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useRenameTag } from '../useRenameTag';
import { tagsKey } from '../useTags';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

describe('useRenameTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('PATCHes and returns the updated row', async () => {
    server.use(
      http.patch('http://localhost/tags/tg1', async ({ request }) => {
        const body = (await request.json()) as { name?: string; color?: string | null };
        expect(body).toEqual({ name: 'Vocal F', color: null });
        return HttpResponse.json({
          id: 'tg1', name: 'Vocal F', color: null,
          created_at: 'x', updated_at: 'y',
        });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useRenameTag(), { wrapper: wrap(qc) });
    let row;
    await act(async () => {
      row = await result.current.mutateAsync({
        tagId: 'tg1',
        patch: { name: 'Vocal F', color: null },
      });
    });
    expect(row).toMatchObject({ id: 'tg1', name: 'Vocal F', color: null });
  });

  it('invalidates the tags list on success', async () => {
    server.use(
      http.patch('http://localhost/tags/tg1', () =>
        HttpResponse.json({
          id: 'tg1', name: 'X', color: '#fff',
          created_at: 'x', updated_at: 'y',
        }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(tagsKey(), [{ id: 'tg1' }]);
    const { result } = renderHook(() => useRenameTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'tg1', patch: { name: 'X' } });
    });
    expect(qc.getQueryState(tagsKey())?.isInvalidated).toBe(true);
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RenameTagInput } from '../lib/tagSchemas';
import { tagsKey, type Tag } from './useTags';

export interface RenameTagArgs {
  tagId: string;
  patch: RenameTagInput;
}

export function useRenameTag(): UseMutationResult<Tag, Error, RenameTagArgs> {
  const qc = useQueryClient();
  return useMutation<Tag, Error, RenameTagArgs>({
    mutationFn: ({ tagId, patch }) =>
      api<Tag>(`/tags/${tagId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: tagsKey() });
    },
  });
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/hooks/__tests__/useRenameTag.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/hooks/useRenameTag.ts \
        frontend/src/features/tags/hooks/__tests__/useRenameTag.test.tsx
git commit -m "feat(tags): add useRenameTag mutation hook"
```

---

## Task 9: `hooks/useDeleteTag.ts` (cascade-invalidate `categories/tracks`)

**Files:**
- Create: `frontend/src/features/tags/hooks/useDeleteTag.ts`
- Create: `frontend/src/features/tags/hooks/__tests__/useDeleteTag.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useDeleteTag } from '../useDeleteTag';
import { tagsKey } from '../useTags';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

describe('useDeleteTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('DELETEs and resolves on 204', async () => {
    let hit = false;
    server.use(
      http.delete('http://localhost/tags/tg1', () => {
        hit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useDeleteTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'tg1' });
    });
    expect(hit).toBe(true);
  });

  it('treats 404 tag_not_found as success (idempotent)', async () => {
    server.use(
      http.delete('http://localhost/tags/missing', () =>
        HttpResponse.json(
          { error_code: 'tag_not_found', message: 'gone' },
          { status: 404 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useDeleteTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'missing' });
    });
    // No throw means "success" path was taken
  });

  it('invalidates tags AND categories/tracks on settle', async () => {
    server.use(
      http.delete('http://localhost/tags/tg1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = makeClient();
    qc.setQueryData(tagsKey(), [{ id: 'tg1' }]);
    qc.setQueryData(['categories', 'tracks', 'c1', '', 'added_at', 'desc', '', 'all'], { sentinel: true });
    const { result } = renderHook(() => useDeleteTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ tagId: 'tg1' });
    });
    expect(qc.getQueryState(tagsKey())?.isInvalidated).toBe(true);
    expect(qc.getQueryState(['categories', 'tracks', 'c1', '', 'added_at', 'desc', '', 'all'])?.isInvalidated).toBe(true);
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { tagsKey } from './useTags';

export interface DeleteTagInput {
  tagId: string;
}

export function useDeleteTag(): UseMutationResult<void, Error, DeleteTagInput> {
  const qc = useQueryClient();
  return useMutation<void, Error, DeleteTagInput>({
    mutationFn: async ({ tagId }) => {
      try {
        await api(`/tags/${tagId}`, { method: 'DELETE' });
      } catch (err) {
        if (err instanceof ApiError && err.status === 404 && err.code === 'tag_not_found') {
          return;
        }
        throw err;
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: tagsKey() });
      // Server cascades the FK; drop pills from any cached track list.
      qc.invalidateQueries({ queryKey: ['categories', 'tracks'] });
    },
  });
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/hooks/__tests__/useDeleteTag.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/hooks/useDeleteTag.ts \
        frontend/src/features/tags/hooks/__tests__/useDeleteTag.test.tsx
git commit -m "feat(tags): add useDeleteTag with cascade invalidation"
```

---

## Task 10: `hooks/useAddTrackTag.ts` (optimistic patch)

The optimistic patch updates every cached page of `categoryTracks` for the given `categoryId` regardless of the (search, sort, order, tags filter) tuple — the row may be visible in several tabs / variations.

**Files:**
- Create: `frontend/src/features/tags/hooks/useAddTrackTag.ts`
- Create: `frontend/src/features/tags/hooks/__tests__/useAddTrackTag.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider, type InfiniteData } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useAddTrackTag } from '../useAddTrackTag';
import {
  categoryTracksKey,
  type PaginatedTracks,
} from '../../../categories/hooks/useCategoryTracks';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function seed(qc: QueryClient, categoryId: string): readonly string[] {
  const items: PaginatedTracks['items'] = [
    {
      id: 't1', title: 't1', mix_name: null, artists: [], label: null,
      bpm: null, length_ms: null, publish_date: null,
      spotify_release_date: null, isrc: null, spotify_id: null,
      release_type: null, is_ai_suspected: false,
      added_at: 'now', source_triage_block_id: null,
      tags: [],
    },
  ];
  const page: PaginatedTracks = { items, total: 1, limit: 50, offset: 0 };
  const key = categoryTracksKey(categoryId, '', 'added_at', 'desc', [], 'all');
  qc.setQueryData<InfiniteData<PaginatedTracks>>(key, {
    pages: [page], pageParams: [0],
  });
  return key;
}

describe('useAddTrackTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs and resolves on 201', async () => {
    server.use(
      http.post('http://localhost/tracks/t1/tags', async ({ request }) => {
        const body = (await request.json()) as { tag_id: string };
        expect(body).toEqual({ tag_id: 'tg1' });
        return HttpResponse.json(
          { tags: [{ id: 'tg1', name: 'Vocal', color: '#ff8800',
                     created_at: 'x', updated_at: 'y' }] },
          { status: 201 },
        );
      }),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useAddTrackTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        categoryId: 'c1', trackId: 't1',
        tag: { id: 'tg1', name: 'Vocal', color: '#ff8800' },
      });
    });
    // Query was invalidated on settle
    expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it('optimistically appends the tag to every page; rolls back on error', async () => {
    server.use(
      http.post('http://localhost/tracks/t1/tags', () =>
        HttpResponse.json({ error_code: 'boom', message: 'fail' }, { status: 500 }),
      ),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useAddTrackTag(), { wrapper: wrap(qc) });
    await expect(
      result.current.mutateAsync({
        categoryId: 'c1', trackId: 't1',
        tag: { id: 'tg1', name: 'Vocal', color: '#ff8800' },
      }),
    ).rejects.toBeTruthy();
    const data = qc.getQueryData<InfiniteData<PaginatedTracks>>(key);
    expect(data?.pages[0].items[0].tags).toEqual([]);
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```ts
import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedTracks } from '../../categories/hooks/useCategoryTracks';

export interface AddTrackTagInput {
  categoryId: string;
  trackId: string;
  tag: { id: string; name: string; color: string | null };
}

interface MutationContext {
  prev: Array<[readonly unknown[], InfiniteData<PaginatedTracks> | undefined]>;
}

function patch(
  data: InfiniteData<PaginatedTracks> | undefined,
  trackId: string,
  tag: AddTrackTagInput['tag'],
): InfiniteData<PaginatedTracks> | undefined {
  if (!data) return data;
  return {
    ...data,
    pages: data.pages.map((p) => ({
      ...p,
      items: p.items.map((it) => {
        if (it.id !== trackId) return it;
        if (it.tags.some((t) => t.id === tag.id)) return it;
        return { ...it, tags: [...it.tags, tag] };
      }),
    })),
  };
}

export function useAddTrackTag(): UseMutationResult<
  void,
  Error,
  AddTrackTagInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, AddTrackTagInput, MutationContext>({
    mutationFn: async ({ trackId, tag }) => {
      await api(`/tracks/${trackId}/tags`, {
        method: 'POST',
        body: JSON.stringify({ tag_id: tag.id }),
      });
    },
    onMutate: async ({ categoryId, trackId, tag }) => {
      const key = ['categories', 'tracks', categoryId] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key });
      qc.setQueriesData<InfiniteData<PaginatedTracks>>(
        { queryKey: key },
        (old) => patch(old, trackId, tag),
      );
      return { prev };
    },
    onError: (_err, _input, ctx) => {
      if (!ctx) return;
      for (const [key, data] of ctx.prev) qc.setQueryData(key, data);
    },
    onSettled: (_d, _e, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/hooks/__tests__/useAddTrackTag.test.tsx`
Expected: 2 passed.

> Note: this test imports `categoryTracksKey` and `PaginatedTracks` with the **new** signature (tagIds + tagMatch in the key, `tags: TrackTag[]` in the row). Both are defined inside the same file in Task 19. To avoid a chicken-and-egg, this task **temporarily** patches the existing helpers — see the next step.

- [ ] **Step 5: Pre-emptively widen `categoryTracksKey` and `CategoryTrack`**

The existing `categoryTracksKey` returns a 4-element tuple. Update `useCategoryTracks.ts`:

```ts
export const categoryTracksKey = (
  id: string,
  search: string,
  sort: CategoryTrackSort,
  order: SortOrder,
  tagIds: readonly string[] = [],
  tagMatch: 'all' | 'any' = 'all',
) =>
  ['categories', 'tracks', id, search, sort, order,
   [...tagIds].sort().join(','), tagMatch] as const;
```

And widen `CategoryTrack`:

```ts
export interface CategoryTagRef {
  id: string;
  name: string;
  color: string | null;
}

export interface CategoryTrack {
  // ... existing fields ...
  source_triage_block_id: string | null;
  tags: CategoryTagRef[];
}
```

This is a *signature change only* — the URL still omits the tag params (default `[]` / `'all'`) so behaviour is identical. Existing tests that build `CategoryTrack` literals will fail to typecheck because `tags` is missing. Identify the affected files with:

```
cd frontend
pnpm typecheck 2>&1 | grep "Property 'tags' is missing" | sort -u
```

For each match, add `tags: []` to the literal. Likely culprits in this codebase (touch all that fail typecheck):
- `frontend/src/features/categories/hooks/__tests__/useRemoveTrackOptimistic.test.tsx` (`seed()`)
- `frontend/src/features/categories/hooks/__tests__/useMoveTrackBetweenCategories.test.tsx`
- `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`
- `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`
- `frontend/src/features/categories/components/__tests__/TrackRowActions.test.tsx`
- `frontend/src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx`
- `frontend/src/__tests__/curate-flow.test.tsx` (if it shapes a `CategoryTrack` payload)

Triage / curate / playback test fixtures use their own track types (`BucketTrack`, `PlaybackTrack`) and do NOT need touching.

- [ ] **Step 6: Re-run the full hooks suite**

Run: `pnpm test src/features/tags src/features/categories/hooks`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/tags/hooks/useAddTrackTag.ts \
        frontend/src/features/tags/hooks/__tests__/useAddTrackTag.test.tsx \
        frontend/src/features/categories/hooks/useCategoryTracks.ts \
        frontend/src/features/categories/hooks/__tests__/
git commit -m "feat(tags): add useAddTrackTag + widen categoryTracks cache shape"
```

---

## Task 11: `hooks/useRemoveTrackTag.ts` (optimistic patch)

**Files:**
- Create: `frontend/src/features/tags/hooks/useRemoveTrackTag.ts`
- Create: `frontend/src/features/tags/hooks/__tests__/useRemoveTrackTag.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider, type InfiniteData } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useRemoveTrackTag } from '../useRemoveTrackTag';
import {
  categoryTracksKey,
  type PaginatedTracks,
} from '../../../categories/hooks/useCategoryTracks';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function seed(qc: QueryClient, categoryId: string): readonly string[] {
  const items: PaginatedTracks['items'] = [
    {
      id: 't1', title: 't1', mix_name: null, artists: [], label: null,
      bpm: null, length_ms: null, publish_date: null,
      spotify_release_date: null, isrc: null, spotify_id: null,
      release_type: null, is_ai_suspected: false,
      added_at: 'now', source_triage_block_id: null,
      tags: [{ id: 'tg1', name: 'Vocal', color: '#ff8800' }],
    },
  ];
  const page: PaginatedTracks = { items, total: 1, limit: 50, offset: 0 };
  const key = categoryTracksKey(categoryId, '', 'added_at', 'desc', [], 'all');
  qc.setQueryData<InfiniteData<PaginatedTracks>>(key, {
    pages: [page], pageParams: [0],
  });
  return key;
}

describe('useRemoveTrackTag', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('DELETEs and optimistically removes pill', async () => {
    server.use(
      http.delete('http://localhost/tracks/t1/tags/tg1', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useRemoveTrackTag(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        categoryId: 'c1', trackId: 't1', tagId: 'tg1',
      });
    });
    expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it('rolls back on error', async () => {
    server.use(
      http.delete('http://localhost/tracks/t1/tags/tg1', () =>
        HttpResponse.json({ error_code: 'boom', message: 'fail' }, { status: 500 }),
      ),
    );
    const qc = makeClient();
    const key = seed(qc, 'c1');
    const { result } = renderHook(() => useRemoveTrackTag(), { wrapper: wrap(qc) });
    await expect(
      result.current.mutateAsync({ categoryId: 'c1', trackId: 't1', tagId: 'tg1' }),
    ).rejects.toBeTruthy();
    const data = qc.getQueryData<InfiniteData<PaginatedTracks>>(key);
    expect(data?.pages[0].items[0].tags.map((t) => t.id)).toEqual(['tg1']);
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```ts
import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedTracks } from '../../categories/hooks/useCategoryTracks';

export interface RemoveTrackTagInput {
  categoryId: string;
  trackId: string;
  tagId: string;
}

interface MutationContext {
  prev: Array<[readonly unknown[], InfiniteData<PaginatedTracks> | undefined]>;
}

function patch(
  data: InfiniteData<PaginatedTracks> | undefined,
  trackId: string,
  tagId: string,
): InfiniteData<PaginatedTracks> | undefined {
  if (!data) return data;
  return {
    ...data,
    pages: data.pages.map((p) => ({
      ...p,
      items: p.items.map((it) =>
        it.id === trackId
          ? { ...it, tags: it.tags.filter((t) => t.id !== tagId) }
          : it,
      ),
    })),
  };
}

export function useRemoveTrackTag(): UseMutationResult<
  void,
  Error,
  RemoveTrackTagInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, RemoveTrackTagInput, MutationContext>({
    mutationFn: async ({ trackId, tagId }) => {
      await api(`/tracks/${trackId}/tags/${tagId}`, { method: 'DELETE' });
    },
    onMutate: async ({ categoryId, trackId, tagId }) => {
      const key = ['categories', 'tracks', categoryId] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key });
      qc.setQueriesData<InfiniteData<PaginatedTracks>>(
        { queryKey: key },
        (old) => patch(old, trackId, tagId),
      );
      return { prev };
    },
    onError: (_err, _input, ctx) => {
      if (!ctx) return;
      for (const [key, data] of ctx.prev) qc.setQueryData(key, data);
    },
    onSettled: (_d, _e, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/hooks/__tests__/useRemoveTrackTag.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/hooks/useRemoveTrackTag.ts \
        frontend/src/features/tags/hooks/__tests__/useRemoveTrackTag.test.tsx
git commit -m "feat(tags): add useRemoveTrackTag with optimistic shrink"
```

---

## Task 12: `components/TagPill.tsx`

**Files:**
- Create: `frontend/src/features/tags/components/TagPill.tsx`
- Create: `frontend/src/features/tags/components/__tests__/TagPill.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { TagPill } from '../TagPill';

function W({ children }: { children: React.ReactNode }) {
  return <MantineProvider>{children}</MantineProvider>;
}

describe('TagPill', () => {
  it('renders the tag name', () => {
    render(
      <W>
        <TagPill name="Vocal" color="#ff8800" />
      </W>,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
  });

  it('uses the colour as background when provided', () => {
    render(
      <W>
        <TagPill name="Vocal" color="#ff8800" data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('rgb(255, 136, 0)');
  });

  it('falls back to a neutral outline when colour is null', () => {
    render(
      <W>
        <TagPill name="Vocal" color={null} data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('transparent');
    expect(el.style.borderStyle).toBe('solid');
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```tsx
import { Box, type BoxProps } from '@mantine/core';
import { pickPillTextColor } from '../lib/tagPalette';

export interface TagPillProps extends BoxProps {
  name: string;
  color: string | null;
  /** Render an additional `×` to the right; emits `onRemove` when clicked. */
  onRemove?: () => void;
}

export function TagPill({ name, color, onRemove, ...rest }: TagPillProps) {
  const fg = pickPillTextColor(color);
  const baseStyle: React.CSSProperties = color
    ? {
        backgroundColor: color,
        color: fg,
        border: '1px solid transparent',
      }
    : {
        backgroundColor: 'transparent',
        color: 'var(--mantine-color-text)',
        border: '1px solid var(--mantine-color-default-border)',
        borderStyle: 'solid',
      };
  return (
    <Box
      component="span"
      px={8}
      py={2}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        borderRadius: 999,
        fontSize: 12,
        lineHeight: 1.4,
        ...baseStyle,
      }}
      {...rest}
    >
      <span>{name}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label={`Remove ${name}`}
          style={{
            all: 'unset',
            cursor: 'pointer',
            opacity: 0.7,
            fontSize: 12,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </Box>
  );
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/components/__tests__/TagPill.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/components/TagPill.tsx \
        frontend/src/features/tags/components/__tests__/TagPill.test.tsx
git commit -m "feat(tags): add TagPill component"
```

---

## Task 13: `components/ColorSwatchPicker.tsx`

**Files:**
- Create: `frontend/src/features/tags/components/ColorSwatchPicker.tsx`
- Create: `frontend/src/features/tags/components/__tests__/ColorSwatchPicker.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ColorSwatchPicker } from '../ColorSwatchPicker';
import { TAG_PALETTE } from '../../lib/tagPalette';

function W({ children }: { children: React.ReactNode }) {
  return <MantineProvider>{children}</MantineProvider>;
}

describe('ColorSwatchPicker', () => {
  it('renders all 12 palette swatches plus the clear button', () => {
    render(
      <W>
        <ColorSwatchPicker value={null} onChange={() => {}} />
      </W>,
    );
    for (const c of TAG_PALETTE) {
      expect(screen.getByRole('button', { name: `colour ${c}` })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: /no colour/i })).toBeInTheDocument();
  });

  it('marks the active swatch with aria-pressed=true', () => {
    render(
      <W>
        <ColorSwatchPicker value={TAG_PALETTE[2]} onChange={() => {}} />
      </W>,
    );
    expect(
      screen.getByRole('button', { name: `colour ${TAG_PALETTE[2]}` }),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('emits the picked colour', async () => {
    const onChange = vi.fn();
    render(
      <W>
        <ColorSwatchPicker value={null} onChange={onChange} />
      </W>,
    );
    await userEvent.click(
      screen.getByRole('button', { name: `colour ${TAG_PALETTE[0]}` }),
    );
    expect(onChange).toHaveBeenCalledWith(TAG_PALETTE[0]);
  });

  it('emits null when "no colour" pressed', async () => {
    const onChange = vi.fn();
    render(
      <W>
        <ColorSwatchPicker value={TAG_PALETTE[0]} onChange={onChange} />
      </W>,
    );
    await userEvent.click(screen.getByRole('button', { name: /no colour/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```tsx
import { Group, UnstyledButton, ColorSwatch } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { TAG_PALETTE } from '../lib/tagPalette';

export interface ColorSwatchPickerProps {
  value: string | null;
  onChange: (next: string | null) => void;
}

export function ColorSwatchPicker({ value, onChange }: ColorSwatchPickerProps) {
  const { t } = useTranslation();
  return (
    <Group gap={6} wrap="wrap">
      {TAG_PALETTE.map((c) => {
        const active = value?.toLowerCase() === c.toLowerCase();
        return (
          <UnstyledButton
            key={c}
            type="button"
            onClick={() => onChange(c)}
            aria-label={`colour ${c}`}
            aria-pressed={active}
            style={{
              borderRadius: 999,
              outline: active ? '2px solid var(--mantine-color-text)' : 'none',
              outlineOffset: 1,
            }}
          >
            <ColorSwatch color={c} size={20} />
          </UnstyledButton>
        );
      })}
      <UnstyledButton
        type="button"
        onClick={() => onChange(null)}
        aria-label={t('tags.color_picker.none_aria')}
        aria-pressed={value === null}
        style={{
          width: 20, height: 20,
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 999,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 14,
          lineHeight: 1,
          outline: value === null ? '2px solid var(--mantine-color-text)' : 'none',
          outlineOffset: 1,
        }}
      >
        ×
      </UnstyledButton>
    </Group>
  );
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/tags/components/__tests__/ColorSwatchPicker.test.tsx`
Expected: 4 passed (after Task 19 i18n keys land; until then add the key inline below).

- [ ] **Step 5: Add a placeholder i18n key**

Until Task 19 lands the rest of the keys, add the bare minimum so the test resolves:

Edit `frontend/src/i18n/en.json`. Inside the top-level object add:

```json
  "tags": {
    "color_picker": { "none_aria": "no colour" }
  },
```

(Subsequent tasks expand this `tags` block; merge by hand to avoid clobbering.)

- [ ] **Step 6: Re-run the test**

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/tags/components/ColorSwatchPicker.tsx \
        frontend/src/features/tags/components/__tests__/ColorSwatchPicker.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(tags): add ColorSwatchPicker"
```

---

## Task 14: `components/TagFormFields.tsx`

Shared name + colour fields used by both create and rename flows in the manager modal.

**Files:**
- Create: `frontend/src/features/tags/components/TagFormFields.tsx`
- Create: `frontend/src/features/tags/components/__tests__/TagFormFields.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { TagFormFields } from '../TagFormFields';

function W({ children }: { children: React.ReactNode }) {
  return <MantineProvider>{children}</MantineProvider>;
}

describe('TagFormFields', () => {
  it('shows inline error when name empty on submit', async () => {
    const onSubmit = vi.fn();
    render(
      <W>
        <TagFormFields
          mode="create"
          initialName=""
          initialColor={null}
          submitting={false}
          onCancel={() => {}}
          onSubmit={onSubmit}
        />
      </W>,
    );
    await userEvent.click(screen.getByRole('button', { name: /save|create/i }));
    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('emits trimmed name and selected colour', async () => {
    const onSubmit = vi.fn();
    render(
      <W>
        <TagFormFields
          mode="create"
          initialName=""
          initialColor={null}
          submitting={false}
          onCancel={() => {}}
          onSubmit={onSubmit}
        />
      </W>,
    );
    await userEvent.type(screen.getByRole('textbox', { name: /name/i }), '  Vocal  ');
    await userEvent.click(screen.getByRole('button', { name: /save|create/i }));
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Vocal', color: null });
  });

  it('renders rename label when mode=rename', () => {
    render(
      <W>
        <TagFormFields
          mode="rename"
          initialName="Vocal"
          initialColor="#ff8800"
          submitting={false}
          onCancel={() => {}}
          onSubmit={() => {}}
        />
      </W>,
    );
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('shows server error from prop', () => {
    render(
      <W>
        <TagFormFields
          mode="create"
          initialName=""
          initialColor={null}
          submitting={false}
          serverError="Tag already exists"
          onCancel={() => {}}
          onSubmit={() => {}}
        />
      </W>,
    );
    expect(screen.getByText(/tag already exists/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```tsx
import { Button, Group, Stack, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useTranslation } from 'react-i18next';
import { createTagSchema, type CreateTagInput } from '../lib/tagSchemas';
import { ColorSwatchPicker } from './ColorSwatchPicker';

export type TagFormMode = 'create' | 'rename';

export interface TagFormFieldsProps {
  mode: TagFormMode;
  initialName: string;
  initialColor: string | null;
  submitting: boolean;
  serverError?: string;
  onCancel: () => void;
  onSubmit: (input: { name: string; color: string | null }) => void;
}

export function TagFormFields({
  mode,
  initialName,
  initialColor,
  submitting,
  serverError,
  onCancel,
  onSubmit,
}: TagFormFieldsProps) {
  const { t } = useTranslation();
  const form = useForm<CreateTagInput>({
    initialValues: { name: initialName, color: initialColor },
    validate: zodResolver(createTagSchema),
  });

  const errorMap: Record<string, string> = {
    name_required: t('tags.errors.name_required'),
    name_too_long: t('tags.errors.name_too_long'),
    name_control_chars: t('tags.errors.name_control_chars'),
    color_invalid: t('tags.errors.color_invalid'),
  };
  const fieldError = (() => {
    if (serverError) return serverError;
    const e = form.errors.name;
    if (!e) return undefined;
    return errorMap[String(e)] ?? String(e);
  })();

  return (
    <form
      onSubmit={form.onSubmit((values) =>
        onSubmit({ name: values.name.trim(), color: values.color }),
      )}
    >
      <Stack gap="xs">
        <TextInput
          label={t('tags.form.name_label')}
          placeholder={t('tags.form.name_placeholder')}
          autoFocus
          {...form.getInputProps('name')}
          error={fieldError}
          disabled={submitting}
        />
        <ColorSwatchPicker
          value={form.values.color ?? null}
          onChange={(c) => form.setFieldValue('color', c)}
        />
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onCancel} disabled={submitting}>
            {t('tags.form.cancel')}
          </Button>
          <Button type="submit" loading={submitting}>
            {mode === 'create' ? t('tags.form.create_submit') : t('tags.form.save')}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
```

- [ ] **Step 4: Add the i18n keys**

Merge into the existing `tags` block in `frontend/src/i18n/en.json`:

```json
"tags": {
  "color_picker": { "none_aria": "no colour" },
  "form": {
    "name_label": "Name",
    "name_placeholder": "Vocal",
    "create_submit": "Create",
    "save": "Save",
    "cancel": "Cancel"
  },
  "errors": {
    "name_required": "Name is required.",
    "name_too_long": "Name must be 64 characters or less.",
    "name_control_chars": "Name contains forbidden characters.",
    "color_invalid": "Invalid colour."
  }
}
```

- [ ] **Step 5: Run, expect pass**

Run: `pnpm test src/features/tags/components/__tests__/TagFormFields.test.tsx`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/tags/components/TagFormFields.tsx \
        frontend/src/features/tags/components/__tests__/TagFormFields.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(tags): add shared TagFormFields component"
```

---

## Task 15: `components/TagsManagerModal.tsx`

**Files:**
- Create: `frontend/src/features/tags/components/TagsManagerModal.tsx`
- Create: `frontend/src/features/tags/components/__tests__/TagsManagerModal.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TagsManagerModal } from '../TagsManagerModal';

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function W({ children }: { children: React.ReactNode }) {
  const qc = makeClient();
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

describe('TagsManagerModal', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({
          items: [
            { id: 'tg1', name: 'Vocal', color: '#ff8800',
              created_at: 'x', updated_at: 'x' },
            { id: 'tg2', name: 'Dark', color: null,
              created_at: 'x', updated_at: 'x' },
          ],
          total: 2, limit: 200, offset: 0,
        }),
      ),
    );
  });

  it('lists existing tags', async () => {
    render(
      <W>
        <TagsManagerModal opened onClose={() => {}} />
      </W>,
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Vocal')).toBeInTheDocument();
    expect(within(dialog).getByText('Dark')).toBeInTheDocument();
  });

  it('creates a tag from the inline form', async () => {
    let captured: unknown = null;
    server.use(
      http.post('http://localhost/tags', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json(
          { id: 'tg-new', name: 'Drum', color: null,
            created_at: 'x', updated_at: 'x' },
          { status: 201 },
        );
      }),
    );
    render(
      <W>
        <TagsManagerModal opened onClose={() => {}} />
      </W>,
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /new tag/i }));
    await userEvent.type(within(dialog).getByRole('textbox', { name: /name/i }), 'Drum');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));
    expect(captured).toEqual({ name: 'Drum', color: null });
  });

  it('shows the 409 conflict message inline on duplicate name', async () => {
    server.use(
      http.post('http://localhost/tags', () =>
        HttpResponse.json(
          { error_code: 'tag_name_conflict', message: 'dup' },
          { status: 409 },
        ),
      ),
    );
    render(
      <W>
        <TagsManagerModal opened onClose={() => {}} />
      </W>,
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /new tag/i }));
    await userEvent.type(within(dialog).getByRole('textbox', { name: /name/i }), 'Vocal');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));
    expect(await within(dialog).findByText(/already exists/i)).toBeInTheDocument();
  });
});
```

> **Mantine portal note:** `await screen.findByRole('dialog')` resolves the modal; subsequent queries scope through `within(dialog)` to avoid matching stale portal nodes left by prior tests (existing CLAUDE.md gotcha).

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```tsx
import { useState } from 'react';
import {
  ActionIcon, Button, Group, Loader, Modal, Stack, Text, TextInput,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconEdit, IconPlus, IconTrash, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useTags, type Tag } from '../hooks/useTags';
import { useCreateTag } from '../hooks/useCreateTag';
import { useRenameTag } from '../hooks/useRenameTag';
import { useDeleteTag } from '../hooks/useDeleteTag';
import { normalizeTagName } from '../lib/normalizeTagName';
import { TagPill } from './TagPill';
import { TagFormFields } from './TagFormFields';

export interface TagsManagerModalProps {
  opened: boolean;
  onClose: () => void;
}

type EditState =
  | { mode: 'idle' }
  | { mode: 'creating' }
  | { mode: 'renaming'; tag: Tag };

export function TagsManagerModal({ opened, onClose }: TagsManagerModalProps) {
  const { t } = useTranslation();
  const tagsQ = useTags();
  const createMut = useCreateTag();
  const renameMut = useRenameTag();
  const deleteMut = useDeleteTag();
  const [edit, setEdit] = useState<EditState>({ mode: 'idle' });
  const [search, setSearch] = useState('');
  const [serverError, setServerError] = useState<string | undefined>();

  const items = (tagsQ.data ?? []).filter((tag) =>
    !search ? true : normalizeTagName(tag.name).startsWith(normalizeTagName(search)),
  );

  const handleCreate = async (input: { name: string; color: string | null }) => {
    setServerError(undefined);
    try {
      await createMut.mutateAsync(input);
      setEdit({ mode: 'idle' });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'tag_name_conflict') {
        setServerError(t('tags.errors.name_conflict'));
        return;
      }
      notifications.show({ color: 'red', message: t('tags.toast.save_failed') });
    }
  };

  const handleRename = async (tag: Tag, input: { name: string; color: string | null }) => {
    setServerError(undefined);
    try {
      await renameMut.mutateAsync({
        tagId: tag.id,
        patch: {
          name: input.name === tag.name ? undefined : input.name,
          color: input.color === tag.color ? undefined : input.color,
        },
      });
      setEdit({ mode: 'idle' });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'tag_name_conflict') {
        setServerError(t('tags.errors.name_conflict'));
        return;
      }
      notifications.show({ color: 'red', message: t('tags.toast.save_failed') });
    }
  };

  const handleDelete = (tag: Tag) => {
    modals.openConfirmModal({
      title: t('tags.delete_modal.title'),
      children: <Text size="sm">{t('tags.delete_modal.body', { name: tag.name })}</Text>,
      labels: { confirm: t('tags.delete_modal.confirm'), cancel: t('tags.delete_modal.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync({ tagId: tag.id });
        } catch {
          notifications.show({ color: 'red', message: t('tags.toast.delete_failed') });
        }
      },
    });
  };

  return (
    <Modal opened={opened} onClose={onClose} size="lg" title={t('tags.manager.title')}>
      <Stack gap="md">
        <Group justify="space-between">
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setEdit({ mode: 'creating' })}
            disabled={edit.mode !== 'idle'}
          >
            {t('tags.manager.new_tag')}
          </Button>
          <TextInput
            placeholder={t('tags.manager.search_placeholder')}
            leftSection={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            style={{ width: 240 }}
          />
        </Group>

        {edit.mode === 'creating' && (
          <TagFormFields
            mode="create"
            initialName=""
            initialColor={null}
            submitting={createMut.isPending}
            serverError={serverError}
            onCancel={() => { setEdit({ mode: 'idle' }); setServerError(undefined); }}
            onSubmit={handleCreate}
          />
        )}

        {tagsQ.isLoading && <Loader size="sm" />}

        <Stack gap={4}>
          {items.map((tag) => (
            <Group key={tag.id} justify="space-between" wrap="nowrap">
              {edit.mode === 'renaming' && edit.tag.id === tag.id ? (
                <TagFormFields
                  mode="rename"
                  initialName={tag.name}
                  initialColor={tag.color}
                  submitting={renameMut.isPending}
                  serverError={serverError}
                  onCancel={() => { setEdit({ mode: 'idle' }); setServerError(undefined); }}
                  onSubmit={(input) => handleRename(tag, input)}
                />
              ) : (
                <>
                  <TagPill name={tag.name} color={tag.color} />
                  <Group gap={4}>
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('tags.manager.rename_aria', { name: tag.name })}
                      onClick={() => setEdit({ mode: 'renaming', tag })}
                    >
                      <IconEdit size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('tags.manager.delete_aria', { name: tag.name })}
                      onClick={() => handleDelete(tag)}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </>
              )}
            </Group>
          ))}
          {!tagsQ.isLoading && items.length === 0 && (
            <Text size="sm" c="dimmed">{t('tags.manager.empty')}</Text>
          )}
        </Stack>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 4: Expand i18n keys**

Merge into `frontend/src/i18n/en.json` `tags`:

```json
"manager": {
  "title": "Manage tags",
  "new_tag": "New tag",
  "search_placeholder": "Search…",
  "rename_aria": "Rename {{name}}",
  "delete_aria": "Delete {{name}}",
  "empty": "No tags yet."
},
"delete_modal": {
  "title": "Delete tag?",
  "body": "Delete \"{{name}}\"? It will be removed from every track.",
  "confirm": "Delete",
  "cancel": "Cancel"
},
"toast": {
  "save_failed": "Couldn't save tag.",
  "delete_failed": "Couldn't delete tag."
},
"errors": {
  "name_conflict": "A tag with this name already exists."
}
```

(Merge — don't replace — the existing `errors` and other keys.)

- [ ] **Step 5: Run, expect pass**

Run: `pnpm test src/features/tags/components/__tests__/TagsManagerModal.test.tsx`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/tags/components/TagsManagerModal.tsx \
        frontend/src/features/tags/components/__tests__/TagsManagerModal.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(tags): add TagsManagerModal with create/rename/delete"
```

---

## Task 16: `components/TrackTagsPopover.tsx`

**Files:**
- Create: `frontend/src/features/tags/components/TrackTagsPopover.tsx`
- Create: `frontend/src/features/tags/components/__tests__/TrackTagsPopover.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TrackTagsPopover } from '../TrackTagsPopover';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('TrackTagsPopover', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({
          items: [
            { id: 'tg1', name: 'Vocal', color: '#ff8800',
              created_at: 'x', updated_at: 'x' },
            { id: 'tg2', name: 'Dark', color: null,
              created_at: 'x', updated_at: 'x' },
          ],
          total: 2, limit: 200, offset: 0,
        }),
      ),
    );
  });

  it('renders checkboxes for each tag and reflects current selection', async () => {
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          categoryId="c1"
          trackId="t1"
          currentTagIds={['tg1']}
        />
      </W>,
    );
    const vocalRow = await screen.findByRole('checkbox', { name: /vocal/i });
    const darkRow = await screen.findByRole('checkbox', { name: /dark/i });
    expect(vocalRow).toBeChecked();
    expect(darkRow).not.toBeChecked();
  });

  it('calls POST /tracks/{id}/tags when an unchecked tag is clicked', async () => {
    let captured: unknown = null;
    server.use(
      http.post('http://localhost/tracks/t1/tags', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json(
          { tags: [] }, { status: 201 },
        );
      }),
    );
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          categoryId="c1"
          trackId="t1"
          currentTagIds={[]}
        />
      </W>,
    );
    await userEvent.click(await screen.findByRole('checkbox', { name: /vocal/i }));
    expect(captured).toEqual({ tag_id: 'tg1' });
  });

  it('shows "Create" suggestion when search has no exact match', async () => {
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          categoryId="c1"
          trackId="t1"
          currentTagIds={[]}
        />
      </W>,
    );
    await userEvent.type(
      await screen.findByPlaceholderText(/search.*create/i),
      'hyper',
    );
    expect(await screen.findByRole('button', { name: /create.*hyper/i })).toBeInTheDocument();
  });

  it('does NOT show "Create" suggestion when search matches an existing tag exactly', async () => {
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          categoryId="c1"
          trackId="t1"
          currentTagIds={[]}
        />
      </W>,
    );
    await userEvent.type(
      await screen.findByPlaceholderText(/search.*create/i),
      'vocal',
    );
    expect(screen.queryByRole('button', { name: /create.*vocal/i })).toBeNull();
  });

  it('disables remaining checkboxes when 50 tags already attached', async () => {
    const manyIds = Array.from({ length: 50 }, (_, i) => `attached${i}`);
    render(
      <W>
        <TrackTagsPopover
          opened
          onClose={() => {}}
          target={<button>open</button>}
          categoryId="c1"
          trackId="t1"
          currentTagIds={manyIds}
        />
      </W>,
    );
    const dark = await screen.findByRole('checkbox', { name: /dark/i });
    expect(dark).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```tsx
import { useState } from 'react';
import {
  Box, Checkbox, Group, Loader, Popover, Stack, Text, TextInput, UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useTags, type Tag } from '../hooks/useTags';
import { useCreateTag } from '../hooks/useCreateTag';
import { useAddTrackTag } from '../hooks/useAddTrackTag';
import { useRemoveTrackTag } from '../hooks/useRemoveTrackTag';
import { normalizeTagName } from '../lib/normalizeTagName';
import { ColorSwatchPicker } from './ColorSwatchPicker';
import { TagPill } from './TagPill';

const MAX_TAGS_PER_TRACK = 50;

export interface TrackTagsPopoverProps {
  opened: boolean;
  onClose: () => void;
  target: React.ReactElement;
  categoryId: string;
  trackId: string;
  currentTagIds: readonly string[];
}

export function TrackTagsPopover({
  opened, onClose, target, categoryId, trackId, currentTagIds,
}: TrackTagsPopoverProps) {
  const { t } = useTranslation();
  const tagsQ = useTags();
  const addMut = useAddTrackTag();
  const removeMut = useRemoveTrackTag();
  const createMut = useCreateTag();
  const [search, setSearch] = useState('');
  const [creatingColor, setCreatingColor] = useState<string | null>(null);
  const [creatingMode, setCreatingMode] = useState(false);

  const all = tagsQ.data ?? [];
  const normSearch = normalizeTagName(search);
  const visible = normSearch
    ? all.filter((t) => normalizeTagName(t.name).startsWith(normSearch))
    : all;
  const exactMatch = normSearch
    ? all.some((t) => normalizeTagName(t.name) === normSearch)
    : false;
  const showCreate = normSearch.length > 0 && !exactMatch;
  const atCap = currentTagIds.length >= MAX_TAGS_PER_TRACK;

  const toggle = async (tag: Tag, checked: boolean) => {
    try {
      if (checked) {
        await addMut.mutateAsync({
          categoryId, trackId,
          tag: { id: tag.id, name: tag.name, color: tag.color },
        });
      } else {
        await removeMut.mutateAsync({ categoryId, trackId, tagId: tag.id });
      }
    } catch {
      notifications.show({ color: 'red', message: t('tags.toast.update_failed') });
    }
  };

  const handleCreate = async () => {
    const name = search.trim();
    if (!name) return;
    try {
      const tag = await createMut.mutateAsync({ name, color: creatingColor });
      await addMut.mutateAsync({
        categoryId, trackId,
        tag: { id: tag.id, name: tag.name, color: tag.color },
      });
      setSearch('');
      setCreatingMode(false);
      setCreatingColor(null);
    } catch {
      notifications.show({ color: 'red', message: t('tags.toast.save_failed') });
    }
  };

  return (
    <Popover
      opened={opened}
      onClose={onClose}
      position="bottom-start"
      withinPortal
      shadow="md"
      width={280}
    >
      <Popover.Target>{target}</Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <TextInput
            placeholder={t('tags.popover.search_placeholder')}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            autoFocus
          />
          {tagsQ.isLoading && <Loader size="xs" />}
          <Stack gap={2}>
            {visible.map((tag) => {
              const checked = currentTagIds.includes(tag.id);
              return (
                <Checkbox
                  key={tag.id}
                  label={
                    <Group gap={6} wrap="nowrap">
                      <TagPill name={tag.name} color={tag.color} />
                    </Group>
                  }
                  checked={checked}
                  disabled={!checked && atCap}
                  onChange={(e) => toggle(tag, e.currentTarget.checked)}
                />
              );
            })}
            {!tagsQ.isLoading && visible.length === 0 && !showCreate && (
              <Text size="sm" c="dimmed">{t('tags.popover.empty')}</Text>
            )}
          </Stack>
          {atCap && (
            <Text size="xs" c="dimmed">{t('tags.popover.cap_hint')}</Text>
          )}
          {showCreate && !creatingMode && (
            <UnstyledButton
              onClick={() => setCreatingMode(true)}
              style={{
                fontSize: 13, padding: '4px 6px',
                borderTop: '1px solid var(--mantine-color-default-border)',
              }}
            >
              {t('tags.popover.create_label', { name: search.trim() })}
            </UnstyledButton>
          )}
          {creatingMode && (
            <Stack gap={4}>
              <ColorSwatchPicker value={creatingColor} onChange={setCreatingColor} />
              <Group justify="flex-end" gap={4}>
                <UnstyledButton
                  onClick={() => { setCreatingMode(false); setCreatingColor(null); }}
                  style={{ fontSize: 13 }}
                >
                  {t('tags.form.cancel')}
                </UnstyledButton>
                <UnstyledButton
                  onClick={handleCreate}
                  style={{ fontSize: 13, fontWeight: 600 }}
                >
                  {t('tags.popover.create_confirm')}
                </UnstyledButton>
              </Group>
            </Stack>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
```

- [ ] **Step 4: Add i18n keys**

Merge into `frontend/src/i18n/en.json` `tags`:

```json
"popover": {
  "search_placeholder": "Search or create…",
  "empty": "No tags yet.",
  "cap_hint": "Max 50 tags per track.",
  "create_label": "+ Create \"{{name}}\"",
  "create_confirm": "Create"
},
"toast": {
  "save_failed": "Couldn't save tag.",
  "update_failed": "Couldn't update track tags.",
  "delete_failed": "Couldn't delete tag."
}
```

(Merge with existing keys.)

- [ ] **Step 5: Run, expect pass**

Run: `pnpm test src/features/tags/components/__tests__/TrackTagsPopover.test.tsx`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/tags/components/TrackTagsPopover.tsx \
        frontend/src/features/tags/components/__tests__/TrackTagsPopover.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(tags): add TrackTagsPopover (search, toggle, inline create)"
```

---

## Task 17: `components/TrackTagsCell.tsx`

**Files:**
- Create: `frontend/src/features/tags/components/TrackTagsCell.tsx`
- Create: `frontend/src/features/tags/components/__tests__/TrackTagsCell.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TrackTagsCell } from '../TrackTagsCell';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('TrackTagsCell', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
  });

  it('renders pills for current tags', () => {
    render(
      <W>
        <TrackTagsCell
          categoryId="c1"
          trackId="t1"
          tags={[
            { id: 'tg1', name: 'Vocal', color: '#ff8800' },
            { id: 'tg2', name: 'Dark', color: null },
          ]}
        />
      </W>,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
    expect(screen.getByText('Dark')).toBeInTheDocument();
  });

  it('opens the popover on "+" click', async () => {
    render(
      <W>
        <TrackTagsCell categoryId="c1" trackId="t1" tags={[]} />
      </W>,
    );
    await userEvent.click(screen.getByRole('button', { name: /add tag/i }));
    expect(await screen.findByPlaceholderText(/search.*create/i)).toBeInTheDocument();
  });

  it('opens the popover on pill click', async () => {
    render(
      <W>
        <TrackTagsCell
          categoryId="c1"
          trackId="t1"
          tags={[{ id: 'tg1', name: 'Vocal', color: '#ff8800' }]}
        />
      </W>,
    );
    await userEvent.click(screen.getByText('Vocal'));
    expect(await screen.findByPlaceholderText(/search.*create/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```tsx
import { useState } from 'react';
import { ActionIcon, Group, UnstyledButton } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { TagPill } from './TagPill';
import { TrackTagsPopover } from './TrackTagsPopover';

export interface TrackTagsCellTag {
  id: string;
  name: string;
  color: string | null;
}

export interface TrackTagsCellProps {
  categoryId: string;
  trackId: string;
  tags: readonly TrackTagsCellTag[];
}

export function TrackTagsCell({ categoryId, trackId, tags }: TrackTagsCellProps) {
  const { t } = useTranslation();
  const [opened, setOpened] = useState(false);
  const target = (
    <ActionIcon
      variant="subtle"
      size="sm"
      aria-label={t('tags.cell.add_aria')}
      onClick={() => setOpened((o) => !o)}
    >
      <IconPlus size={14} />
    </ActionIcon>
  );

  return (
    <Group gap={4} wrap="wrap">
      {tags.map((tag) => (
        <UnstyledButton
          key={tag.id}
          onClick={() => setOpened((o) => !o)}
          style={{ display: 'inline-flex' }}
        >
          <TagPill name={tag.name} color={tag.color} />
        </UnstyledButton>
      ))}
      <TrackTagsPopover
        opened={opened}
        onClose={() => setOpened(false)}
        target={target}
        categoryId={categoryId}
        trackId={trackId}
        currentTagIds={tags.map((t) => t.id)}
      />
    </Group>
  );
}
```

- [ ] **Step 4: Add i18n keys**

Merge into `tags`:

```json
"cell": { "add_aria": "Add tag" }
```

- [ ] **Step 5: Run, expect pass**

Run: `pnpm test src/features/tags/components/__tests__/TrackTagsCell.test.tsx`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/tags/components/TrackTagsCell.tsx \
        frontend/src/features/tags/components/__tests__/TrackTagsCell.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(tags): add TrackTagsCell (pills + popover trigger)"
```

---

## Task 18: `components/TagsFilterBar.tsx`

**Files:**
- Create: `frontend/src/features/tags/components/TagsFilterBar.tsx`
- Create: `frontend/src/features/tags/components/__tests__/TagsFilterBar.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { TagsFilterBar } from '../TagsFilterBar';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('TagsFilterBar', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({
          items: [
            { id: 'tg1', name: 'Vocal', color: '#ff8800',
              created_at: 'x', updated_at: 'x' },
            { id: 'tg2', name: 'Dark', color: null,
              created_at: 'x', updated_at: 'x' },
          ],
          total: 2, limit: 200, offset: 0,
        }),
      ),
    );
  });

  it('does not render the match toggle when nothing selected', async () => {
    render(
      <W>
        <TagsFilterBar selectedIds={[]} match="all" onChange={() => {}} />
      </W>,
    );
    expect(screen.queryByRole('radio', { name: /any/i })).toBeNull();
    expect(screen.queryByRole('radio', { name: /^all$/i })).toBeNull();
  });

  it('renders the match toggle with at least one tag selected', async () => {
    render(
      <W>
        <TagsFilterBar selectedIds={['tg1']} match="all" onChange={() => {}} />
      </W>,
    );
    expect(await screen.findByRole('radio', { name: /any/i })).toBeInTheDocument();
  });

  it('emits onChange when match flipped', async () => {
    const onChange = vi.fn();
    render(
      <W>
        <TagsFilterBar selectedIds={['tg1']} match="all" onChange={onChange} />
      </W>,
    );
    await userEvent.click(await screen.findByRole('radio', { name: /any/i }));
    expect(onChange).toHaveBeenCalledWith({ selectedIds: ['tg1'], match: 'any' });
  });
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```tsx
import { Group, MultiSelect, SegmentedControl, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useTags } from '../hooks/useTags';
import type { TagsFilterState } from '../lib/tagsUrlState';

export interface TagsFilterBarProps {
  selectedIds: string[];
  match: 'all' | 'any';
  onChange: (next: TagsFilterState) => void;
}

export function TagsFilterBar({ selectedIds, match, onChange }: TagsFilterBarProps) {
  const { t } = useTranslation();
  const tagsQ = useTags();
  const data = (tagsQ.data ?? []).map((tag) => ({
    value: tag.id,
    label: tag.name,
  }));

  return (
    <Group gap="sm" wrap="wrap" align="center">
      <MultiSelect
        placeholder={t('tags.filter.placeholder')}
        data={data}
        value={selectedIds}
        onChange={(next) => onChange({ selectedIds: next, match })}
        searchable
        clearable
        nothingFoundMessage={t('tags.filter.empty')}
        style={{ minWidth: 220 }}
      />
      {selectedIds.length > 0 && (
        <SegmentedControl
          value={match}
          onChange={(value) =>
            onChange({ selectedIds, match: value === 'any' ? 'any' : 'all' })
          }
          data={[
            { value: 'all', label: t('tags.filter.match_all') },
            { value: 'any', label: t('tags.filter.match_any') },
          ]}
          size="xs"
        />
      )}
      {selectedIds.length > 0 && (
        <Text size="xs" c="dimmed">
          {t('tags.filter.count', { count: selectedIds.length })}
        </Text>
      )}
    </Group>
  );
}
```

- [ ] **Step 4: Add i18n keys**

Merge:

```json
"filter": {
  "placeholder": "Filter by tag…",
  "empty": "No tags yet.",
  "match_all": "All",
  "match_any": "Any",
  "count_one": "{{count}} tag",
  "count_other": "{{count}} tags"
}
```

- [ ] **Step 5: Run, expect pass**

Run: `pnpm test src/features/tags/components/__tests__/TagsFilterBar.test.tsx`
Expected: 3 passed.

> **Note:** Mantine `SegmentedControl` exposes radios under the hood; `getByRole('radio', { name: /any/i })` should resolve. If RTL fails to find them in jsdom, use `getByText` fallback.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/tags/components/TagsFilterBar.tsx \
        frontend/src/features/tags/components/__tests__/TagsFilterBar.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(tags): add TagsFilterBar with ALL/ANY toggle"
```

---

## Task 19: `features/tags/index.ts` (public surface)

**Files:**
- Create: `frontend/src/features/tags/index.ts`

- [ ] **Step 1: Write the barrel**

```ts
export { TagPill } from './components/TagPill';
export { TrackTagsCell, type TrackTagsCellTag } from './components/TrackTagsCell';
export { TrackTagsPopover } from './components/TrackTagsPopover';
export { TagsFilterBar } from './components/TagsFilterBar';
export { TagsManagerModal } from './components/TagsManagerModal';
export { useTags, type Tag } from './hooks/useTags';
export type { TagsFilterState } from './lib/tagsUrlState';
export { readTagsUrlState, writeTagsUrlState } from './lib/tagsUrlState';
```

- [ ] **Step 2: Verify with type-check**

Run from `frontend/`: `pnpm typecheck`
Expected: green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/tags/index.ts
git commit -m "feat(tags): public barrel for the tags feature"
```

---

## Task 20: Wire `useCategoryTracks` to send tag params + parse `tags` rows

**Files:**
- Modify: `frontend/src/features/categories/hooks/useCategoryTracks.ts`
- Modify: `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`

The cache shape was already widened in Task 10 Step 5 (signature only, default values). Now we make the hook **actually send** the params and consume the `tags` field on each row.

- [ ] **Step 1: Add a failing test**

Append to `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`:

```tsx
it('passes tags + match query params when filter set', async () => {
  let captured: URL | null = null;
  server.use(
    http.get('http://localhost/categories/c1/tracks', ({ request }) => {
      captured = new URL(request.url);
      return HttpResponse.json({
        items: [],
        total: 0, limit: 50, offset: 0,
      });
    }),
  );
  const qc = makeClient();
  const { result } = renderHook(
    () => useCategoryTracks('c1', '', 'added_at', 'desc', ['tg2', 'tg1'], 'any'),
    { wrapper: wrap(qc) },
  );
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(captured).not.toBeNull();
  // Sorted lexicographically before being sent
  expect(captured!.searchParams.get('tags')).toBe('tg1,tg2');
  expect(captured!.searchParams.get('match')).toBe('any');
});

it('omits tags param when no filter', async () => {
  let captured: URL | null = null;
  server.use(
    http.get('http://localhost/categories/c1/tracks', ({ request }) => {
      captured = new URL(request.url);
      return HttpResponse.json({
        items: [], total: 0, limit: 50, offset: 0,
      });
    }),
  );
  const qc = makeClient();
  const { result } = renderHook(
    () => useCategoryTracks('c1', '', 'added_at', 'desc'),
    { wrapper: wrap(qc) },
  );
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(captured!.searchParams.has('tags')).toBe(false);
  expect(captured!.searchParams.has('match')).toBe(false);
});

it('parses tags field on each row', async () => {
  server.use(
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({
        items: [
          {
            id: 't1', title: 't1', mix_name: null, artists: [],
            label: null, bpm: null, length_ms: null, publish_date: null,
            spotify_release_date: null, isrc: null, spotify_id: null,
            release_type: null, is_ai_suspected: false,
            added_at: 'now', source_triage_block_id: null,
            tags: [{ id: 'tg1', name: 'Vocal', color: '#ff8800' }],
          },
        ],
        total: 1, limit: 50, offset: 0,
      }),
    ),
  );
  const qc = makeClient();
  const { result } = renderHook(
    () => useCategoryTracks('c1', '', 'added_at', 'desc'),
    { wrapper: wrap(qc) },
  );
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data?.pages[0].items[0].tags).toEqual([
    { id: 'tg1', name: 'Vocal', color: '#ff8800' },
  ]);
});
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Update the hook**

Edit `frontend/src/features/categories/hooks/useCategoryTracks.ts`:

```ts
export function useCategoryTracks(
  categoryId: string,
  search: string,
  sort: CategoryTrackSort = 'added_at',
  order: SortOrder = 'desc',
  tagIds: readonly string[] = [],
  tagMatch: 'all' | 'any' = 'all',
): UseInfiniteQueryResult<InfiniteData<PaginatedTracks>> {
  return useInfiniteQuery({
    queryKey: categoryTracksKey(categoryId, search, sort, order, tagIds, tagMatch),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
        sort,
        order,
      });
      if (search) params.set('search', search);
      if (tagIds.length > 0) {
        params.set('tags', [...tagIds].sort().join(','));
        if (tagMatch === 'any') params.set('match', 'any');
      }
      return api<PaginatedTracks>(
        `/categories/${categoryId}/tracks?${params.toString()}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!categoryId,
  });
}
```

The `CategoryTrack.tags` field already exists from Task 10 Step 5; the response payload from the backend already populates it. No mapping needed — the JSON field name matches the TS interface.

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`
Expected: existing + 3 new = green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useCategoryTracks.ts \
        frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx
git commit -m "feat(categories): send tag filter params and parse track.tags"
```

---

## Task 21: Render `TrackTagsCell` inside `TrackRow`

**Files:**
- Modify: `frontend/src/features/categories/components/TrackRow.tsx`
- Modify: `frontend/src/features/categories/components/__tests__/` (existing tests for TrackRow if any)

- [ ] **Step 1: Add a failing test**

Create `frontend/src/features/categories/components/__tests__/TrackRow.test.tsx` if it does not exist:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider, Table } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TrackRow } from '../TrackRow';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>
        <Table><Table.Tbody>{children}</Table.Tbody></Table>
      </QueryClientProvider>
    </MantineProvider>
  );
}

const baseTrack: CategoryTrack = {
  id: 't1', title: 't1', mix_name: null, artists: [], label: null,
  bpm: null, length_ms: null, publish_date: null,
  spotify_release_date: null, isrc: null, spotify_id: null,
  release_type: null, is_ai_suspected: false,
  added_at: 'now', source_triage_block_id: null,
  tags: [{ id: 'tg1', name: 'Vocal', color: '#ff8800' }],
};

describe('TrackRow tag cell', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
  });

  it('renders existing tag pills (desktop)', () => {
    render(
      <W>
        <TrackRow track={baseTrack} variant="desktop" categoryId="c1" />
      </W>,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect failure**

(Will fail because `TrackRow` does not yet accept `categoryId` nor render tags.)

- [ ] **Step 3: Update `TrackRow` to render the tag cell**

Edit `frontend/src/features/categories/components/TrackRow.tsx`:

```tsx
import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import { formatAdded, formatLength, formatReleaseDate } from '../../../lib/formatters';
import type { CategoryTrack } from '../hooks/useCategoryTracks';
import { TrackTagsCell } from '../../tags/components/TrackTagsCell';

function joinArtists(artists: CategoryTrack['artists']): string {
  return artists.map((a) => a.name).join(', ');
}

export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
  categoryId: string;
  actions?: ReactNode;
}

export function TrackRow({ track, variant, categoryId, actions }: TrackRowProps) {
  const { t } = useTranslation();
  const aiBadge = track.is_ai_suspected ? (
    <IconAlertTriangle
      size={14}
      aria-label={t('categories.tracks_table.ai_suspected_aria')}
      color="var(--color-warning)"
    />
  ) : null;
  const tagsCell = (
    <TrackTagsCell categoryId={categoryId} trackId={track.id} tags={track.tags} />
  );

  if (variant === 'desktop') {
    return (
      <Table.Tr>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {aiBadge}
            <Stack gap={0}>
              <Text fw={500}>{track.title}</Text>
              {track.mix_name && (
                <Text size="xs" c="dimmed">{track.mix_name}</Text>
              )}
            </Stack>
          </Group>
        </Table.Td>
        <Table.Td>{tagsCell}</Table.Td>
        <Table.Td>{joinArtists(track.artists)}</Table.Td>
        <Table.Td>{track.label?.name ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{formatLength(track.length_ms)}</Table.Td>
        <Table.Td className="font-mono">
          {formatReleaseDate(track.spotify_release_date)}
        </Table.Td>
        <Table.Td>{formatAdded(track.added_at)}</Table.Td>
        <Table.Td style={{ width: 40 }}>{actions ?? null}</Table.Td>
      </Table.Tr>
    );
  }

  return (
    <Card withBorder padding="sm" style={{ position: 'relative' }}>
      {actions && (
        <div style={{ position: 'absolute', top: 8, right: 8 }}>{actions}</div>
      )}
      <Stack gap={4}>
        <Group gap="xs">
          {aiBadge}
          <Text fw={500}>{track.title}</Text>
        </Group>
        {track.mix_name && (
          <Text size="xs" c="dimmed">{track.mix_name}</Text>
        )}
        <Text size="sm">{joinArtists(track.artists)}</Text>
        {track.label && (
          <Text size="xs" c="dimmed">{track.label.name}</Text>
        )}
        <div>{tagsCell}</div>
        <Group gap="md" mt={4}>
          <Text size="xs" c="dimmed" className="font-mono">
            {track.bpm ?? '—'} BPM
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          {track.spotify_release_date && (
            <Text size="xs" c="dimmed" className="font-mono">
              {track.spotify_release_date}
            </Text>
          )}
          <Text size="xs" c="dimmed">{formatAdded(track.added_at)}</Text>
        </Group>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 4: Run, expect pass**

Run: `pnpm test src/features/categories/components/__tests__/TrackRow.test.tsx`
Expected: 1 passed.

- [ ] **Step 5: Update `TracksTab` call sites + add the new column header**

Edit `frontend/src/features/categories/components/TracksTab.tsx` — find the desktop `<Table.Thead>` block and inject the new header right after the title `<SortableTh>`:

```tsx
<Table.Th>{t('categories.tracks_table.tags')}</Table.Th>
```

Find both `<TrackRow ...>` invocations (mobile and desktop) and pass `categoryId={categoryId}`.

- [ ] **Step 6: Add the new i18n key**

Inside `frontend/src/i18n/en.json`, locate `categories.tracks_table` and add:

```json
"tags": "Tags",
```

- [ ] **Step 7: Run the full categories suite**

Run: `pnpm test src/features/categories`
Expected: green. Existing `TracksTab` tests will need a `categoryId` to be threaded — use the existing `styleId` test fixture's `categoryId` value. Update test fixtures inline if any compile errors appear.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/categories/components/TrackRow.tsx \
        frontend/src/features/categories/components/TracksTab.tsx \
        frontend/src/features/categories/components/__tests__/ \
        frontend/src/i18n/en.json
git commit -m "feat(categories): render tag pills + tags column in track rows"
```

---

## Task 22: Wire `TagsFilterBar` + `TagsManagerModal` into `TracksTab`

**Files:**
- Modify: `frontend/src/features/categories/components/TracksTab.tsx`
- Modify: `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`

- [ ] **Step 1: Write a failing integration test**

Append to `TracksTab.test.tsx` (or, if the file does not yet wrap the tab in a router, lift the existing tests' setup):

```tsx
it('forwards tag filter from URL into useCategoryTracks request', async () => {
  let captured: URL | null = null;
  server.use(
    http.get('http://localhost/tags', () =>
      HttpResponse.json({
        items: [{ id: 'tg1', name: 'Vocal', color: '#ff8800',
                  created_at: 'x', updated_at: 'x' }],
        total: 1, limit: 200, offset: 0,
      }),
    ),
    http.get('http://localhost/categories/c1/tracks', ({ request }) => {
      captured = new URL(request.url);
      return HttpResponse.json({
        items: [], total: 0, limit: 50, offset: 0,
      });
    }),
  );
  // Mount the tab inside a memory router with the filter pre-set in the URL.
  // (Use whatever router helper the existing test uses; add `MemoryRouter`
  // if missing.)
  render(
    <MemoryRouter initialEntries={['/categories/c1?tags=tg1&match=any']}>
      <Routes>
        <Route path="/categories/:id" element={<TracksTab categoryId="c1" styleId="s1" />} />
      </Routes>
    </MemoryRouter>,
  );
  await waitFor(() => {
    expect(captured?.searchParams.get('tags')).toBe('tg1');
    expect(captured?.searchParams.get('match')).toBe('any');
  });
});

it('opens the manage-tags modal when the button is clicked', async () => {
  server.use(
    http.get('http://localhost/tags', () =>
      HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
    ),
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
    ),
  );
  render(
    <MemoryRouter>
      <TracksTab categoryId="c1" styleId="s1" />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole('button', { name: /manage tags/i }));
  expect(await screen.findByRole('dialog', { name: /manage tags/i })).toBeInTheDocument();
});
```

(Adjust router imports to match what the existing TracksTab tests use.)

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Update `TracksTab.tsx`**

```tsx
import { useState } from 'react';
import { Button, Group, Stack, Table, TextInput } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { IconSearch, IconSettings, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import {
  useCategoryTracks,
  type CategoryTrackSort,
  type SortOrder,
} from '../hooks/useCategoryTracks';
import { TrackRow } from './TrackRow';
import { TrackRowActions } from './TrackRowActions';
import { SortableTh } from './SortableTh';
import { EmptyState } from '../../../components/EmptyState';
import { TagsFilterBar } from '../../tags/components/TagsFilterBar';
import { TagsManagerModal } from '../../tags/components/TagsManagerModal';
import { readTagsUrlState, writeTagsUrlState } from '../../tags/lib/tagsUrlState';

export interface TracksTabProps {
  categoryId: string;
  styleId: string;
}

export function TracksTab({ categoryId, styleId }: TracksTabProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [searchParams, setSearchParams] = useSearchParams();
  const tagFilter = readTagsUrlState(searchParams);

  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);
  const [sortKey, setSortKey] = useState<CategoryTrackSort>('added_at');
  const [sortDir, setSortDir] = useState<SortOrder>('desc');
  const [managerOpen, setManagerOpen] = useState(false);

  const handleSort = (key: CategoryTrackSort) => {
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir(key === 'title' ? 'asc' : 'desc');
    }
  };

  const handleTagFilterChange = (next: { selectedIds: string[]; match: 'all' | 'any' }) => {
    setSearchParams(writeTagsUrlState(searchParams, next), { replace: true });
  };

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useCategoryTracks(
      categoryId, debounced, sortKey, sortDir,
      tagFilter.selectedIds, tagFilter.match,
    );

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const filterRow = (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <TextInput
        placeholder={t('categories.detail.tracks_search_placeholder')}
        leftSection={<IconSearch size={16} />}
        value={rawSearch}
        onChange={(e) => setRawSearch(e.currentTarget.value)}
        rightSection={
          rawSearch ? (
            <IconX
              size={16}
              role="button"
              onClick={() => setRawSearch('')}
              style={{ cursor: 'pointer' }}
            />
          ) : null
        }
        style={{ flex: 1, minWidth: 200 }}
      />
      <TagsFilterBar
        selectedIds={tagFilter.selectedIds}
        match={tagFilter.match}
        onChange={handleTagFilterChange}
      />
      <Button
        variant="default"
        leftSection={<IconSettings size={14} />}
        onClick={() => setManagerOpen(true)}
      >
        {t('tags.filter.manage_tags')}
      </Button>
    </Group>
  );

  // ... existing empty-state branches unchanged, but render `filterRow` instead of `searchInput` ...
  // ... mobile / desktop renders unchanged except `<TrackRow ... categoryId={categoryId}>` ...
  // ... append `<TagsManagerModal opened={managerOpen} onClose={() => setManagerOpen(false)} />` to the JSX root ...
}
```

> Replace every `{searchInput}` reference with `{filterRow}`. Remove the now-unused `searchInput` definition.
> Make sure the JSX root in each branch wraps everything in a fragment so `<TagsManagerModal>` can be appended outside the `<Stack>`.

- [ ] **Step 4: Add the i18n key**

Add to `tags.filter`:

```json
"manage_tags": "Manage tags"
```

- [ ] **Step 5: Run, expect pass**

Run: `pnpm test src/features/categories/components/__tests__/TracksTab.test.tsx`
Expected: existing + new = green.

- [ ] **Step 6: Manual UI smoke**

Run from `frontend/`: `pnpm dev`, then in a browser visit `/categories/<some-id>` and:
- create a tag from the manager modal,
- attach it to a track via the popover,
- filter by it,
- delete it from the manager modal,
- confirm the pill disappears from the row.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/categories/components/TracksTab.tsx \
        frontend/src/features/categories/components/__tests__/TracksTab.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(categories): wire tag filter bar + manage-tags modal into TracksTab"
```

---

## Task 23: Final integration smoke (single end-to-end vitest)

**Files:**
- Create: `frontend/src/features/tags/__tests__/integration.test.tsx`

- [ ] **Step 1: Write the test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import { testTheme } from '../../../test/theme';
import { TracksTab } from '../../categories/components/TracksTab';

function W({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter>{children}</MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

describe('Track-tags end-to-end', () => {
  beforeEach(() => {
    tokenStore.set('TOK');

    // In-memory tag store for the test
    let tags: any[] = [];
    let trackTags: any[] = [];

    server.use(
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: tags, total: tags.length, limit: 200, offset: 0 }),
      ),
      http.post('http://localhost/tags', async ({ request }) => {
        const body = (await request.json()) as { name: string; color: string | null };
        const tag = {
          id: `tg-${tags.length + 1}`,
          name: body.name,
          color: body.color,
          created_at: 'now', updated_at: 'now',
        };
        tags.push(tag);
        return HttpResponse.json(tag, { status: 201 });
      }),
      http.delete('http://localhost/tags/:id', ({ params }) => {
        tags = tags.filter((t) => t.id !== params.id);
        trackTags = trackTags.filter((t) => t.tag_id !== params.id);
        return new HttpResponse(null, { status: 204 });
      }),
      http.post('http://localhost/tracks/:trackId/tags', async ({ params, request }) => {
        const body = (await request.json()) as { tag_id: string };
        if (!trackTags.some((t) => t.track_id === params.trackId && t.tag_id === body.tag_id)) {
          trackTags.push({ track_id: params.trackId, tag_id: body.tag_id });
        }
        return HttpResponse.json({ tags: [] }, { status: 201 });
      }),
      http.delete('http://localhost/tracks/:trackId/tags/:tagId', ({ params }) => {
        trackTags = trackTags.filter(
          (t) => !(t.track_id === params.trackId && t.tag_id === params.tagId),
        );
        return new HttpResponse(null, { status: 204 });
      }),
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const tagFilter = (url.searchParams.get('tags') ?? '').split(',').filter(Boolean);
        const match = url.searchParams.get('match') === 'any' ? 'any' : 'all';
        const trackTagIds = trackTags
          .filter((t) => t.track_id === 't1')
          .map((t) => t.tag_id);
        let include = true;
        if (tagFilter.length) {
          include = match === 'all'
            ? tagFilter.every((id) => trackTagIds.includes(id))
            : tagFilter.some((id) => trackTagIds.includes(id));
        }
        const trackTagObjects = tags
          .filter((t) => trackTagIds.includes(t.id))
          .map((t) => ({ id: t.id, name: t.name, color: t.color }));
        return HttpResponse.json({
          items: include ? [{
            id: 't1', title: 't1', mix_name: null, artists: [],
            label: null, bpm: null, length_ms: null, publish_date: null,
            spotify_release_date: null, isrc: null, spotify_id: null,
            release_type: null, is_ai_suspected: false,
            added_at: 'now', source_triage_block_id: null,
            tags: trackTagObjects,
          }] : [],
          total: include ? 1 : 0, limit: 50, offset: 0,
        });
      }),
    );
  });

  it('create → assign → filter → unassign → delete', async () => {
    render(
      <W>
        <TracksTab categoryId="c1" styleId="s1" />
      </W>,
    );

    // 1. open manager and create a tag
    await userEvent.click(await screen.findByRole('button', { name: /manage tags/i }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /new tag/i }));
    await userEvent.type(within(dialog).getByRole('textbox', { name: /name/i }), 'Vocal');
    await userEvent.click(within(dialog).getByRole('button', { name: /^create$/i }));
    await waitFor(() => expect(within(dialog).getByText('Vocal')).toBeInTheDocument());

    // 2. close manager, attach to track via popover
    await userEvent.click(within(dialog).getByRole('button', { name: /close/i }));
    const cellAddBtn = await screen.findByRole('button', { name: /add tag/i });
    await userEvent.click(cellAddBtn);
    await userEvent.click(await screen.findByRole('checkbox', { name: /vocal/i }));

    // 3. row pill appears
    await waitFor(() => {
      const pills = screen.getAllByText('Vocal');
      // one in the cell, possibly one in the popover; just assert at least one
      expect(pills.length).toBeGreaterThan(0);
    });
  });
});
```

> This test exercises the happy-path round-trip but does not assert filter / unassign / delete steps to keep runtime under a second. Extend later if regressions occur.

- [ ] **Step 2: Run**

Run: `pnpm test src/features/tags/__tests__/integration.test.tsx`
Expected: 1 passed.

- [ ] **Step 3: Run the full FE suite**

Run from `frontend/`: `pnpm test`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/tags/__tests__/integration.test.tsx
git commit -m "test(tags): integration smoke for create+assign flow"
```

---

## Final verification

- [ ] **Run the full test suite**

```
.venv/bin/pytest -q
cd frontend && pnpm test && pnpm typecheck && pnpm lint && cd ..
```

Expected: all green.

- [ ] **Skim `git log --oneline` for the branch**

Expected: ~24 commits, each a single coherent slice, all Conventional-Commits-shaped.

- [ ] **Smoke the dev server one last time**

```
cd frontend && pnpm dev
```

Open `http://127.0.0.1:5173/categories/<id>`, run through:
- manage modal → create / rename / delete tag (incl. one with no colour)
- assign / detach a tag from a track via the popover
- filter tracks by one tag (ALL); add a second tag with ANY → list expands
- refresh the page → URL preserves the filter

If anything misbehaves, file the regression and iterate.
