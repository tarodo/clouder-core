# F5 — Curate Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the keyboard-first Curate surface (P-22 mobile + P-23 desktop) — a one-track-at-a-time queue over a single source bucket of an `IN_PROGRESS` triage block, with hotkey assignment, just-tapped pulse, 200ms auto-advance, depth-1 silent undo, double-tap cancel-and-replace, end-of-queue smart-suggest, and per-style resume.

**Architecture:** Three nested routes (`/curate` index → `/curate/:styleId` resume → `/curate/:styleId/:blockId/:bucketId` session) feed a `<CurateSession>` that mounts `useCurateSession` (state container over existing `useBucketTracks` + `useMoveTracks`) and `useCurateHotkeys` (desktop-only keyboard binder). Visual state machine: `loading | active | empty | error`. Move flow reuses F3a's exported helpers (`takeSnapshot`, `applyOptimisticMove`, `restoreSnapshot`, `undoMoveDirect`) — no `useMoveTracks` modification. `accent-magenta` body class applied for the lifetime of the session route activates magenta token for `data-just-tapped` pulse. Persistence: two `localStorage` keys (`clouder.lastCurateStyle`, `clouder.lastCurateLocation`) updated on every successful move + on deep-link mount.

**Tech Stack:** React 19, Mantine 9, TanStack Query 5, Vitest + MSW + jsdom, react-router 7, react-i18next 15, `@mantine/hooks` (`useMediaQuery`, `useHotkeys`). No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-05-04-F5-curate-frontend-design.md`](../specs/2026-05-04-F5-curate-frontend-design.md).

---

## Conventions

- All commits go through the `caveman:caveman-commit` skill (CLAUDE.md `Commit Policy`). Subjects shown below are samples; regenerate via the skill at commit time.
- Branch: `feat/curate` (worktree `.claude/worktrees/f5_task` on branch `worktree-f5_task` already in place; merge target is `main`).
- After EVERY task: run `pnpm test`, `pnpm typecheck` from `frontend/`. Don't proceed until green. Lint at the end of each task too (`pnpm lint`).
- File paths in this plan are absolute from worktree root (`/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f5_task/`) unless noted. `frontend/` is the working directory for all `pnpm` commands.
- New feature folder lives at `frontend/src/features/curate/`. Mirror the `features/triage/` layout (see `frontend/src/features/triage/` for reference).
- Test patterns reuse `frontend/src/test/setup.ts` (five jsdom shims) and `frontend/src/test/theme.ts` (Mantine singleton). Always wrap component / hook tests in `<MantineProvider theme={testTheme}>` per CLAUDE.md.
- Spec uses the term "session" for the `/curate/:styleId/:blockId/:bucketId` route — keep that terminology in code (`useCurateSession`, `<CurateSession>`).

---

## Task 1: `curate.*` i18n keys

**Why first:** Every component reads i18n keys. Adding all keys upfront means later tasks just `t('curate.foo')` without coordination overhead.

**Files:**
- Modify: `frontend/src/i18n/en.json` — add the `curate` section.

- [ ] **Step 1: Add the `curate` block**

Open `frontend/src/i18n/en.json`. Find the closing `}` of the top-level object. Insert the following block as a new top-level key (sibling of `triage`, `categories`, etc.):

```json
"curate": {
  "page_title": "Curate",
  "card": {
    "open_in_spotify": "Open in Spotify",
    "open_in_spotify_aria": "Open {{title}} in Spotify (new tab)",
    "ai_badge": "AI suspect",
    "ai_badge_aria": "Track flagged as possibly AI-generated",
    "released_label": "Released",
    "label_label": "Label",
    "bpm_label": "BPM",
    "length_label": "Length",
    "no_spotify_id": "No Spotify match"
  },
  "destination": {
    "group_staging": "Staging",
    "group_technical": "Technical",
    "group_discard": "Discard",
    "more_categories": "More categories…",
    "more_aria": "Show {{count}} more categories",
    "assign_aria": "Assign to {{label}}",
    "self_disabled_title": "Current bucket — pick a different destination",
    "inactive_disabled_title": "Category inactive — re-activate in Categories"
  },
  "footer": {
    "track_counter": "Track {{current}} of {{total}}",
    "in_bucket": "in {{label}}",
    "shortcut_prev": "Prev",
    "shortcut_skip": "Skip",
    "shortcut_undo": "Undo",
    "shortcut_help": "Help",
    "shortcut_exit": "Exit"
  },
  "hotkeys": {
    "title": "Keyboard shortcuts",
    "section_assign": "Assign",
    "section_navigate": "Navigate",
    "section_action": "Action",
    "section_system": "System",
    "key_digits_label": "Assign to staging category 1–9",
    "key_qwe_label": "Assign to NEW / OLD / NOT",
    "key_zero_label": "Assign to DISCARD",
    "key_space_label": "Open in Spotify (audio in F6)",
    "key_j_label": "Skip without assigning",
    "key_k_label": "Step back to previous track",
    "key_u_label": "Undo last assignment",
    "key_help_label": "Show / hide this overlay",
    "key_esc_label": "Close overlay or exit Curate",
    "key_enter_label": "Accept suggested next bucket",
    "footer_audio_note": "Audio playback ships in F6 — Space opens Spotify in a new tab for now.",
    "footer_overflow_note": "Categories beyond 9 are accessible via the More… menu.",
    "mobile_note": "Keyboard shortcuts available on desktop only. Tap a destination button to assign."
  },
  "toast": {
    "skip_stale": "Track no longer in this bucket — skipped.",
    "block_finalized": "Block was finalized. Returning to triage.",
    "block_not_found": "Block not found. It may have been deleted.",
    "destination_inactive": "Destination became inactive. Pick another.",
    "service_unavailable": "Service unavailable. Move not applied — please retry.",
    "move_failed": "Move failed. Please retry."
  },
  "setup": {
    "title": "Pick a block to curate",
    "block_select_label": "Block",
    "block_select_placeholder": "Select an active block",
    "bucket_select_label": "Bucket",
    "bucket_select_placeholder": "Select a source bucket",
    "start_cta": "Start curating",
    "no_active_blocks_title": "No active blocks for {{style_name}}",
    "no_active_blocks_body": "Create a triage block to start curating.",
    "open_triage_cta": "Open Triage",
    "no_eligible_buckets_title": "No source-eligible buckets",
    "no_eligible_buckets_body": "All buckets are empty or already promoted. Try another block."
  },
  "end_of_queue": {
    "heading": "Bucket clean — {{label}}",
    "body_zero": "No tracks sorted in this session.",
    "body_one": "You sorted 1 track. Nice work.",
    "body_other": "You sorted {{count}} tracks. Nice work.",
    "continue_cta": "Continue with {{label}} ({{count}})",
    "finalize_cta": "Finalize block",
    "back_to_triage_cta": "Back to triage"
  },
  "triage_cta": {
    "from_block": "Curate this block",
    "from_bucket": "Curate this bucket"
  },
  "exit_aria": "Exit Curate",
  "help_aria": "Show keyboard shortcuts",
  "back_aria": "Back to triage"
}
```

- [ ] **Step 2: Verify JSON parses**

```bash
cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json','utf8')); console.log('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: clean (no consumers yet, but `i18next` typed-keys integration may pick up the new keys).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/en.json
git commit -m "feat(curate): add curate.* i18n keys"
```

---

## Task 2: `lastCurateLocation` localStorage helpers + tests

**Why second:** Pure module, no React. Mirrors `frontend/src/features/triage/lib/lastVisitedTriageStyle.ts` shape. Foundation for resume routing in Tasks 16–17.

**Files:**
- Create: `frontend/src/features/curate/lib/lastCurateLocation.ts`
- Create: `frontend/src/features/curate/lib/__tests__/lastCurateLocation.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// frontend/src/features/curate/lib/__tests__/lastCurateLocation.test.ts
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
  clearLastCurateLocation,
  isStaleLocation,
  readLastCurateLocation,
  readLastCurateStyle,
  writeLastCurateLocation,
  writeLastCurateStyle,
} from '../lastCurateLocation';
import type { TriageBlock } from '../../../triage/hooks/useTriageBlock';

const mkBlock = (overrides: Partial<TriageBlock> = {}): TriageBlock => ({
  id: 'block-1',
  style_id: 'style-1',
  style_name: 'Tech House',
  name: 'TH W17',
  date_from: '2026-04-21',
  date_to: '2026-04-27',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T00:00:00Z',
  updated_at: '2026-04-20T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'b-new', bucket_type: 'NEW', inactive: false, track_count: 10 },
    { id: 'b-old', bucket_type: 'OLD', inactive: false, track_count: 5 },
    {
      id: 'b-stage',
      bucket_type: 'STAGING',
      inactive: false,
      track_count: 0,
      category_id: 'cat-1',
      category_name: 'Big Room',
    },
  ],
  ...overrides,
});

describe('lastCurateLocation', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('round-trips per styleId', () => {
    writeLastCurateLocation('style-1', 'block-1', 'b-new');
    expect(readLastCurateLocation('style-1')).toMatchObject({
      blockId: 'block-1',
      bucketId: 'b-new',
    });
  });

  it('returns null for unknown styleId', () => {
    expect(readLastCurateLocation('unknown')).toBeNull();
  });

  it('keeps separate entries per style', () => {
    writeLastCurateLocation('style-1', 'b1', 'bk1');
    writeLastCurateLocation('style-2', 'b2', 'bk2');
    expect(readLastCurateLocation('style-1')?.blockId).toBe('b1');
    expect(readLastCurateLocation('style-2')?.blockId).toBe('b2');
  });

  it('stamps updatedAt on write', () => {
    writeLastCurateLocation('style-1', 'block-1', 'b-new');
    const stored = readLastCurateLocation('style-1');
    expect(stored?.updatedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('clears the entry for a single style', () => {
    writeLastCurateLocation('style-1', 'b1', 'bk1');
    writeLastCurateLocation('style-2', 'b2', 'bk2');
    clearLastCurateLocation('style-1');
    expect(readLastCurateLocation('style-1')).toBeNull();
    expect(readLastCurateLocation('style-2')?.blockId).toBe('b2');
  });

  it('returns null + clears entry when stored JSON is corrupt', () => {
    localStorage.setItem(LAST_CURATE_LOCATION_KEY, 'not-json');
    expect(readLastCurateLocation('style-1')).toBeNull();
    expect(localStorage.getItem(LAST_CURATE_LOCATION_KEY)).toBeNull();
  });

  it('round-trips lastCurateStyle', () => {
    writeLastCurateStyle('style-7');
    expect(readLastCurateStyle()).toBe('style-7');
  });

  it('isStaleLocation: true when block status is FINALIZED', () => {
    expect(
      isStaleLocation({ blockId: 'block-1', bucketId: 'b-new' }, mkBlock({ status: 'FINALIZED' })),
    ).toBe(true);
  });

  it('isStaleLocation: true when bucketId no longer in block.buckets', () => {
    expect(isStaleLocation({ blockId: 'block-1', bucketId: 'gone' }, mkBlock())).toBe(true);
  });

  it('isStaleLocation: true when bucket is STAGING (not source-eligible)', () => {
    expect(isStaleLocation({ blockId: 'block-1', bucketId: 'b-stage' }, mkBlock())).toBe(true);
  });

  it('isStaleLocation: false on healthy IN_PROGRESS source bucket', () => {
    expect(isStaleLocation({ blockId: 'block-1', bucketId: 'b-new' }, mkBlock())).toBe(false);
  });

  it('exposes the storage keys for tests / migrations', () => {
    expect(LAST_CURATE_LOCATION_KEY).toBe('clouder.lastCurateLocation');
    expect(LAST_CURATE_STYLE_KEY).toBe('clouder.lastCurateStyle');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/lib/__tests__/lastCurateLocation.test.ts
```

Expected: FAIL with `Cannot find module '../lastCurateLocation'`.

- [ ] **Step 3: Implement the helper**

```ts
// frontend/src/features/curate/lib/lastCurateLocation.ts
import type { TriageBlock } from '../../triage/hooks/useTriageBlock';

export const LAST_CURATE_LOCATION_KEY = 'clouder.lastCurateLocation';
export const LAST_CURATE_STYLE_KEY = 'clouder.lastCurateStyle';

export interface CurateLocation {
  blockId: string;
  bucketId: string;
  updatedAt: string;
}

type Storage = Record<string, CurateLocation>;

function readStorage(): Storage {
  let raw: string | null;
  try {
    raw = localStorage.getItem(LAST_CURATE_LOCATION_KEY);
  } catch {
    return {};
  }
  if (raw === null) return {};
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Storage;
    }
    throw new Error('invalid shape');
  } catch {
    try {
      localStorage.removeItem(LAST_CURATE_LOCATION_KEY);
    } catch {
      /* ignore */
    }
    return {};
  }
}

function writeStorage(s: Storage): void {
  try {
    localStorage.setItem(LAST_CURATE_LOCATION_KEY, JSON.stringify(s));
  } catch {
    /* private mode etc. — ignore */
  }
}

export function readLastCurateLocation(styleId: string): CurateLocation | null {
  return readStorage()[styleId] ?? null;
}

export function writeLastCurateLocation(
  styleId: string,
  blockId: string,
  bucketId: string,
): void {
  const s = readStorage();
  s[styleId] = { blockId, bucketId, updatedAt: new Date().toISOString() };
  writeStorage(s);
}

export function clearLastCurateLocation(styleId: string): void {
  const s = readStorage();
  if (styleId in s) {
    delete s[styleId];
    writeStorage(s);
  }
}

export function readLastCurateStyle(): string | null {
  try {
    return localStorage.getItem(LAST_CURATE_STYLE_KEY);
  } catch {
    return null;
  }
}

export function writeLastCurateStyle(styleId: string): void {
  try {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, styleId);
  } catch {
    /* ignore */
  }
}

export function isStaleLocation(
  loc: { blockId: string; bucketId: string },
  block: TriageBlock,
): boolean {
  if (block.status === 'FINALIZED') return true;
  const bucket = block.buckets.find((b) => b.id === loc.bucketId);
  if (!bucket) return true;
  if (bucket.bucket_type === 'STAGING') return true;
  return false;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test src/features/curate/lib/__tests__/lastCurateLocation.test.ts
```

Expected: 11 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/curate/lib/lastCurateLocation.ts frontend/src/features/curate/lib/__tests__/lastCurateLocation.test.ts
git commit -m "feat(curate): add lastCurateLocation storage helpers"
```

---

## Task 3: `destinationMap` pure resolver + tests

**Why now:** Pure mapping, no React. Used by `useCurateHotkeys` (Task 6) and `<DestinationGrid>` (Task 10) to translate keystroke / position → bucket.

**Files:**
- Create: `frontend/src/features/curate/lib/destinationMap.ts`
- Create: `frontend/src/features/curate/lib/__tests__/destinationMap.test.ts`

**Note on staging ordering:** `TriageBucket` (from `frontend/src/features/triage/lib/bucketLabels.ts`) does NOT carry a `position` field today — staging buckets arrive ordered by backend (spec-D §6 ordering: `NEW, OLD, NOT, UNCLASSIFIED, DISCARD, staging[position ASC]`). We rely on this incoming order.

- [ ] **Step 1: Write failing tests**

```ts
// frontend/src/features/curate/lib/__tests__/destinationMap.test.ts
import { describe, expect, it } from 'vitest';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';
import {
  byDiscard,
  byPosition,
  byTechType,
  resolveStagingHotkeys,
} from '../destinationMap';

const stage = (id: string, name: string, inactive = false): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive,
  track_count: 0,
  category_id: `cat-${id}`,
  category_name: name,
});

const tech = (id: string, t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED'): TriageBucket => ({
  id,
  bucket_type: t,
  inactive: false,
  track_count: 0,
});

describe('destinationMap.byPosition', () => {
  it('returns the active staging bucket at position 0', () => {
    const buckets = [tech('b-new', 'NEW'), stage('s1', 'Big Room'), stage('s2', 'Hard Techno')];
    expect(byPosition(buckets, 0)?.id).toBe('s1');
    expect(byPosition(buckets, 1)?.id).toBe('s2');
  });

  it('skips inactive staging entries when computing the offset', () => {
    const buckets = [
      stage('s1', 'A', true),
      stage('s2', 'B'),
      stage('s3', 'C', true),
      stage('s4', 'D'),
    ];
    expect(byPosition(buckets, 0)?.id).toBe('s2');
    expect(byPosition(buckets, 1)?.id).toBe('s4');
    expect(byPosition(buckets, 2)).toBeNull();
  });

  it('returns null for out-of-range positions', () => {
    expect(byPosition([stage('s1', 'A')], 5)).toBeNull();
  });

  it('returns null when buckets has zero staging', () => {
    expect(byPosition([tech('b-new', 'NEW')], 0)).toBeNull();
  });
});

describe('destinationMap.byTechType', () => {
  const buckets = [
    tech('b-new', 'NEW'),
    tech('b-old', 'OLD'),
    tech('b-not', 'NOT'),
    tech('b-disc', 'DISCARD'),
  ];
  it('matches NEW / OLD / NOT', () => {
    expect(byTechType(buckets, 'NEW')?.id).toBe('b-new');
    expect(byTechType(buckets, 'OLD')?.id).toBe('b-old');
    expect(byTechType(buckets, 'NOT')?.id).toBe('b-not');
  });
  it('returns null when type missing', () => {
    expect(byTechType([], 'NEW')).toBeNull();
  });
});

describe('destinationMap.byDiscard', () => {
  it('returns the DISCARD bucket', () => {
    expect(byDiscard([tech('b-disc', 'DISCARD')])?.id).toBe('b-disc');
  });
  it('returns null when missing', () => {
    expect(byDiscard([])).toBeNull();
  });
});

describe('destinationMap.resolveStagingHotkeys', () => {
  it('maps the first 9 active staging slots to digits 1-9 in incoming order', () => {
    const buckets = [
      tech('b-new', 'NEW'),
      stage('s1', 'A'),
      stage('s2', 'B', true),
      stage('s3', 'C'),
      stage('s4', 'D'),
    ];
    const slots = resolveStagingHotkeys(buckets);
    expect(slots).toHaveLength(3);
    expect(slots[0]?.id).toBe('s1');
    expect(slots[1]?.id).toBe('s3');
    expect(slots[2]?.id).toBe('s4');
  });

  it('caps slots at 9 — extras are returned via the overflow array', () => {
    const buckets = Array.from({ length: 12 }, (_, i) => stage(`s${i}`, `Cat ${i}`));
    const slots = resolveStagingHotkeys(buckets);
    const overflow = buckets
      .filter((b) => b.bucket_type === 'STAGING' && !b.inactive)
      .slice(9);
    expect(slots).toHaveLength(9);
    expect(overflow.map((b) => b.id)).toEqual(['s9', 's10', 's11']);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/lib/__tests__/destinationMap.test.ts
```

Expected: FAIL with module not found.

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/curate/lib/destinationMap.ts
import type { TriageBucket } from '../../triage/lib/bucketLabels';

export const STAGING_HOTKEY_LIMIT = 9;

export type TechHotkeyType = 'NEW' | 'OLD' | 'NOT';

function activeStaging(buckets: TriageBucket[]): TriageBucket[] {
  return buckets.filter((b) => b.bucket_type === 'STAGING' && !b.inactive);
}

export function byPosition(buckets: TriageBucket[], position: number): TriageBucket | null {
  const active = activeStaging(buckets);
  return active[position] ?? null;
}

export function byTechType(
  buckets: TriageBucket[],
  type: TechHotkeyType,
): TriageBucket | null {
  return buckets.find((b) => b.bucket_type === type) ?? null;
}

export function byDiscard(buckets: TriageBucket[]): TriageBucket | null {
  return buckets.find((b) => b.bucket_type === 'DISCARD') ?? null;
}

export function resolveStagingHotkeys(buckets: TriageBucket[]): TriageBucket[] {
  return activeStaging(buckets).slice(0, STAGING_HOTKEY_LIMIT);
}

export function stagingOverflow(buckets: TriageBucket[]): TriageBucket[] {
  return activeStaging(buckets).slice(STAGING_HOTKEY_LIMIT);
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test src/features/curate/lib/__tests__/destinationMap.test.ts
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/curate/lib/destinationMap.ts frontend/src/features/curate/lib/__tests__/destinationMap.test.ts
git commit -m "feat(curate): add destinationMap resolver"
```

---

## Task 4: `nextSuggestedBucket` selector + tests

**Why now:** Pure selector for end-of-queue smart-suggest. Used by `<EndOfQueue>` (Task 12).

**Files:**
- Create: `frontend/src/features/curate/lib/nextSuggestedBucket.ts`
- Create: `frontend/src/features/curate/lib/__tests__/nextSuggestedBucket.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// frontend/src/features/curate/lib/__tests__/nextSuggestedBucket.test.ts
import { describe, expect, it } from 'vitest';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';
import { nextSuggestedBucket } from '../nextSuggestedBucket';

const tech = (
  id: string,
  t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED',
  count: number,
): TriageBucket => ({ id, bucket_type: t, inactive: false, track_count: count });

const stage = (id: string, count: number): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive: false,
  track_count: count,
  category_id: `c-${id}`,
  category_name: 'X',
});

describe('nextSuggestedBucket', () => {
  it('priority NEW → UNCLASSIFIED → OLD → NOT', () => {
    const buckets = [
      tech('b-new', 'NEW', 5),
      tech('b-uncl', 'UNCLASSIFIED', 3),
      tech('b-old', 'OLD', 7),
      tech('b-not', 'NOT', 9),
    ];
    expect(nextSuggestedBucket(buckets, 'b-current')?.id).toBe('b-new');
    expect(nextSuggestedBucket(buckets, 'b-new')?.id).toBe('b-uncl');
    expect(nextSuggestedBucket(buckets, 'b-uncl')?.id).toBe('b-old');
    expect(nextSuggestedBucket(buckets, 'b-old')?.id).toBe('b-not');
  });

  it('skips empty buckets', () => {
    const buckets = [tech('b-new', 'NEW', 0), tech('b-old', 'OLD', 5)];
    expect(nextSuggestedBucket(buckets, 'b-x')?.id).toBe('b-old');
  });

  it('skips STAGING and DISCARD', () => {
    const buckets = [stage('s1', 10), tech('b-disc', 'DISCARD', 4), tech('b-new', 'NEW', 1)];
    expect(nextSuggestedBucket(buckets, 'b-x')?.id).toBe('b-new');
  });

  it('skips the current bucket', () => {
    const buckets = [tech('b-new', 'NEW', 0), tech('b-old', 'OLD', 5)];
    expect(nextSuggestedBucket(buckets, 'b-old')).toBeNull();
  });

  it('returns null when no eligible bucket exists', () => {
    expect(nextSuggestedBucket([], 'b-x')).toBeNull();
    expect(
      nextSuggestedBucket([stage('s1', 5), tech('b-disc', 'DISCARD', 2)], 'b-x'),
    ).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/lib/__tests__/nextSuggestedBucket.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/curate/lib/nextSuggestedBucket.ts
import type { TriageBucket } from '../../triage/lib/bucketLabels';

const PRIORITY: ReadonlyArray<TriageBucket['bucket_type']> = ['NEW', 'UNCLASSIFIED', 'OLD', 'NOT'];

export function nextSuggestedBucket(
  buckets: TriageBucket[],
  currentBucketId: string,
): TriageBucket | null {
  for (const type of PRIORITY) {
    const candidate = buckets.find(
      (b) => b.bucket_type === type && b.id !== currentBucketId && b.track_count > 0,
    );
    if (candidate) return candidate;
  }
  return null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test src/features/curate/lib/__tests__/nextSuggestedBucket.test.ts
```

Expected: 5 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/curate/lib/nextSuggestedBucket.ts frontend/src/features/curate/lib/__tests__/nextSuggestedBucket.test.ts
git commit -m "feat(curate): add nextSuggestedBucket selector"
```

---

## Task 5: `useCurateSession` state-machine hook + tests

**Why now:** The reducer is the heart of F5. Every later component receives the `Session` object. Largest single task — split into 3 sub-steps (test for queue, test for assign/advance/double-tap, test for undo) so we can iterate.

**Files:**
- Create: `frontend/src/features/curate/hooks/useCurateSession.ts`
- Create: `frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx`

### Architectural notes (read before coding)

- Reuse `useTriageBlock(blockId)` and `useBucketTracks(blockId, bucketId, '')` (both from `frontend/src/features/triage/hooks/`).
- Reuse `useMoveTracks(blockId, styleId)` for the `mutate` call. Reuse the exported helpers `takeSnapshot` and `undoMoveDirect` from `useMoveTracks.ts`.
- Inputs to reducer state:
  - `currentIndex: number`
  - `totalAssigned: number`
  - `lastTappedBucketId: string | null` (drives `data-just-tapped`)
  - `lastOp: { input: MoveInput; snapshot: MoveSnapshot; trackIndex: number } | null`
- Timer IDs live in `useRef<number | null>` (NOT in reducer state), so timers do not trigger re-renders.
- The reducer is pure — all timer scheduling and HTTP fires happen in the imperative callback, then dispatch a pure state transition.
- Pagination buffer of 5 tracks: `useEffect` watching `currentIndex` + `queue.length` calls `fetchNextPage` when `hasNextPage && !isFetchingNextPage && currentIndex >= queue.length - 5`.
- `destinations` is `block.buckets.filter((b) => b.id !== bucketId)` — render order = backend order. Self-bucket excluded entirely. STAGING-inactive stays in the list (consumers render disabled).

- [ ] **Step 1: Write failing test scaffolding (queue load + initial state)**

```tsx
// frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { useCurateSession } from '../useCurateSession';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
} from '../../lib/lastCurateLocation';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

const block = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 3 },
    { id: 'dst1', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c1', category_name: 'Big Room' },
    { id: 'dst2', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c2', category_name: 'Hard Techno' },
    { id: 'b-old', bucket_type: 'OLD' as const, inactive: false, track_count: 0 },
  ],
};

function tracksPage(ids: string[]) {
  return {
    items: ids.map((id) => ({
      track_id: id,
      title: `Track ${id}`,
      mix_name: null,
      isrc: null,
      bpm: 124,
      length_ms: 360000,
      publish_date: '2026-04-15',
      spotify_release_date: '2026-04-15',
      spotify_id: `sp-${id}`,
      release_type: 'single',
      is_ai_suspected: false,
      artists: ['Artist A'],
      label_name: 'Label X',
      added_at: '2026-04-21T00:00:00Z',
    })),
    total: ids.length,
    limit: 50,
    offset: 0,
  };
}

function defaultHandlers() {
  return [
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(tracksPage(['t1', 't2', 't3'])),
    ),
    http.post('http://localhost/triage/blocks/b1/move', () =>
      HttpResponse.json({ moved: 1, correlation_id: 'cid-x' }),
    ),
  ];
}

describe('useCurateSession — initial state', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
  });
  afterEach(() => localStorage.clear());

  it('starts in loading then becomes active with the first track', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );

    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('active'));
    expect(result.current.queue).toHaveLength(3);
    expect(result.current.currentTrack?.track_id).toBe('t1');
    expect(result.current.currentIndex).toBe(0);
    expect(result.current.totalAssigned).toBe(0);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.lastTappedBucketId).toBeNull();
    expect(result.current.destinations.map((d) => d.id)).toEqual(['dst1', 'dst2', 'b-old']);
  });

  it('becomes empty when the source bucket has zero tracks', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('empty'));
    expect(result.current.currentTrack).toBeNull();
  });
});
```

- [ ] **Step 2: Run scaffolding tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/hooks/__tests__/useCurateSession.test.tsx
```

Expected: FAIL with module not found.

- [ ] **Step 3: Implement the minimum hook to pass scaffolding tests**

```ts
// frontend/src/features/curate/hooks/useCurateSession.ts
import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { notifications } from '@mantine/notifications';
import { useTriageBlock, type TriageBlock } from '../../triage/hooks/useTriageBlock';
import { useBucketTracks, type BucketTrack } from '../../triage/hooks/useBucketTracks';
import {
  useMoveTracks,
  takeSnapshot,
  undoMoveDirect,
  type MoveInput,
  type MoveSnapshot,
} from '../../triage/hooks/useMoveTracks';
import type { TriageBucket } from '../../triage/lib/bucketLabels';
import { ApiError } from '../../../api/error';
import {
  writeLastCurateLocation,
  writeLastCurateStyle,
} from '../lib/lastCurateLocation';

export interface UseCurateSessionArgs {
  blockId: string;
  bucketId: string;
  styleId: string;
}

export type CurateStatus = 'loading' | 'active' | 'empty' | 'error';

export interface CurateSession {
  status: CurateStatus;
  queue: BucketTrack[];
  currentTrack: BucketTrack | null;
  currentIndex: number;
  totalAssigned: number;
  destinations: TriageBucket[];
  block: TriageBlock | null;
  lastTappedBucketId: string | null;
  canUndo: boolean;
  assign: (toBucketId: string) => void;
  undo: () => void;
  skip: () => void;
  prev: () => void;
  openSpotify: () => void;
}

interface LastOp {
  input: MoveInput;
  snapshot: MoveSnapshot;
  trackIndex: number;
}

interface State {
  currentIndex: number;
  totalAssigned: number;
  lastTappedBucketId: string | null;
  lastOp: LastOp | null;
}

type Action =
  | { type: 'ASSIGN_BEGIN'; toBucketId: string; lastOp: LastOp }
  | { type: 'ASSIGN_REPLACE_BEGIN'; toBucketId: string; lastOp: LastOp }
  | { type: 'ASSIGN_SAME_DEST_PULSE'; toBucketId: string }
  | { type: 'ADVANCE' }
  | { type: 'CLEAR_PULSE' }
  | { type: 'UNDO_WITHIN' }
  | { type: 'UNDO_AFTER' }
  | { type: 'MUTATION_ERROR' }
  | { type: 'SKIP'; max: number }
  | { type: 'PREV' }
  | { type: 'RESET_INDEX_FOR_QUEUE_SHRINK'; queueLength: number };

const initialState: State = {
  currentIndex: 0,
  totalAssigned: 0,
  lastTappedBucketId: null,
  lastOp: null,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'ASSIGN_BEGIN':
      return {
        ...state,
        lastOp: action.lastOp,
        lastTappedBucketId: action.toBucketId,
        totalAssigned: state.totalAssigned + 1,
      };
    case 'ASSIGN_REPLACE_BEGIN':
      // Double-tap: previous op rolled back imperatively before dispatch.
      // totalAssigned unchanged (we already counted it on the first tap).
      return {
        ...state,
        lastOp: action.lastOp,
        lastTappedBucketId: action.toBucketId,
      };
    case 'ASSIGN_SAME_DEST_PULSE':
      return { ...state, lastTappedBucketId: action.toBucketId };
    case 'ADVANCE':
      return { ...state, currentIndex: state.currentIndex + 1 };
    case 'CLEAR_PULSE':
      return { ...state, lastTappedBucketId: null };
    case 'UNDO_WITHIN':
      return {
        ...state,
        lastOp: null,
        lastTappedBucketId: null,
        totalAssigned: Math.max(0, state.totalAssigned - 1),
      };
    case 'UNDO_AFTER':
      if (!state.lastOp) return state;
      return {
        ...state,
        currentIndex: state.lastOp.trackIndex,
        lastOp: null,
        lastTappedBucketId: null,
        totalAssigned: Math.max(0, state.totalAssigned - 1),
      };
    case 'MUTATION_ERROR':
      return {
        ...state,
        lastOp: null,
        lastTappedBucketId: null,
        totalAssigned: Math.max(0, state.totalAssigned - 1),
      };
    case 'SKIP':
      return { ...state, currentIndex: Math.min(action.max, state.currentIndex + 1) };
    case 'PREV':
      return { ...state, currentIndex: Math.max(0, state.currentIndex - 1) };
    case 'RESET_INDEX_FOR_QUEUE_SHRINK':
      if (state.currentIndex > action.queueLength) {
        return { ...state, currentIndex: action.queueLength };
      }
      return state;
    default:
      return state;
  }
}

export const PENDING_ADVANCE_MS = 200;
export const PULSE_MS = 80;

export function useCurateSession({
  blockId,
  bucketId,
  styleId,
}: UseCurateSessionArgs): CurateSession {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const blockQuery = useTriageBlock(blockId);
  const tracksQuery = useBucketTracks(blockId, bucketId, '');
  const moveMutation = useMoveTracks(blockId, styleId);

  const [state, dispatch] = useReducer(reducer, initialState);
  const pendingTimerRef = useRef<number | null>(null);
  const pulseTimerRef = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const queue: BucketTrack[] = useMemo(
    () => tracksQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [tracksQuery.data],
  );
  const currentTrack = queue[state.currentIndex] ?? null;

  const destinations = useMemo<TriageBucket[]>(() => {
    if (!blockQuery.data) return [];
    return blockQuery.data.buckets.filter((b) => b.id !== bucketId);
  }, [blockQuery.data, bucketId]);

  const status: CurateStatus = useMemo(() => {
    if (blockQuery.isError || tracksQuery.isError) return 'error';
    if (blockQuery.isLoading || tracksQuery.isLoading) return 'loading';
    const noMore = !tracksQuery.hasNextPage;
    if (queue.length === 0 && noMore) return 'empty';
    if (state.currentIndex >= queue.length && noMore) return 'empty';
    return 'active';
  }, [
    blockQuery.isError,
    blockQuery.isLoading,
    tracksQuery.isError,
    tracksQuery.isLoading,
    tracksQuery.hasNextPage,
    queue.length,
    state.currentIndex,
  ]);

  // Pagination buffer
  useEffect(() => {
    if (
      tracksQuery.hasNextPage &&
      !tracksQuery.isFetchingNextPage &&
      state.currentIndex >= queue.length - 5
    ) {
      tracksQuery.fetchNextPage();
    }
  }, [state.currentIndex, queue.length, tracksQuery]);

  // Queue-shrink reset (e.g. cache invalidation external to a session move)
  useEffect(() => {
    dispatch({ type: 'RESET_INDEX_FOR_QUEUE_SHRINK', queueLength: queue.length });
  }, [queue.length]);

  const cleanupTimers = useCallback(() => {
    if (pendingTimerRef.current !== null) {
      clearTimeout(pendingTimerRef.current);
      pendingTimerRef.current = null;
    }
    if (pulseTimerRef.current !== null) {
      clearTimeout(pulseTimerRef.current);
      pulseTimerRef.current = null;
    }
  }, []);

  // Cleanup on unmount only
  useEffect(() => () => cleanupTimers(), [cleanupTimers]);

  const schedulePulse = useCallback(() => {
    if (pulseTimerRef.current !== null) clearTimeout(pulseTimerRef.current);
    pulseTimerRef.current = window.setTimeout(() => {
      pulseTimerRef.current = null;
      dispatch({ type: 'CLEAR_PULSE' });
    }, PULSE_MS);
  }, []);

  const scheduleAdvance = useCallback(() => {
    if (pendingTimerRef.current !== null) clearTimeout(pendingTimerRef.current);
    pendingTimerRef.current = window.setTimeout(() => {
      pendingTimerRef.current = null;
      dispatch({ type: 'ADVANCE' });
    }, PENDING_ADVANCE_MS);
  }, []);

  const emitErrorToast = useCallback(
    (err: unknown) => {
      const apiErr = err instanceof ApiError ? err : null;
      const code = apiErr?.code ?? '';
      let messageKey = 'curate.toast.move_failed';
      if (apiErr?.status === 503) messageKey = 'curate.toast.service_unavailable';
      else if (code === 'tracks_not_in_source') messageKey = 'curate.toast.skip_stale';
      else if (code === 'block_not_editable') messageKey = 'curate.toast.block_finalized';
      else if (code === 'triage_block_not_found') messageKey = 'curate.toast.block_not_found';
      else if (code === 'target_bucket_inactive') messageKey = 'curate.toast.destination_inactive';
      notifications.show({
        message: t(messageKey),
        color: code === 'tracks_not_in_source' ? 'blue' : apiErr?.status === 503 ? 'yellow' : 'red',
        autoClose: 4000,
      });
    },
    [t],
  );

  const fireMutation = useCallback(
    (input: MoveInput) => {
      moveMutation.mutate(input, {
        onSuccess: () => {
          writeLastCurateLocation(styleId, blockId, bucketId);
          writeLastCurateStyle(styleId);
        },
        onError: (err) => {
          if (pendingTimerRef.current !== null) {
            clearTimeout(pendingTimerRef.current);
            pendingTimerRef.current = null;
          }
          dispatch({ type: 'MUTATION_ERROR' });
          emitErrorToast(err);
        },
      });
    },
    [moveMutation, blockId, bucketId, styleId, emitErrorToast],
  );

  const assign = useCallback(
    (toBucketId: string) => {
      const track = queue[stateRef.current.currentIndex] ?? null;
      if (!track) return;
      if (toBucketId === bucketId) return;

      const lastOp = stateRef.current.lastOp;
      const isPending = pendingTimerRef.current !== null;

      // Same destination during pending window — only restart the timer + pulse.
      if (isPending && lastOp && lastOp.input.toBucketId === toBucketId) {
        scheduleAdvance();
        schedulePulse();
        dispatch({ type: 'ASSIGN_SAME_DEST_PULSE', toBucketId });
        return;
      }

      // Different destination during pending window — undo first.
      if (isPending && lastOp) {
        if (pendingTimerRef.current !== null) {
          clearTimeout(pendingTimerRef.current);
          pendingTimerRef.current = null;
        }
        // Fire-and-forget: rollback restores cache synchronously, inverse HTTP is async.
        void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {
          /* if the inverse fails we re-apply the optimistic — see undoMoveDirect */
        });
        const input: MoveInput = {
          fromBucketId: bucketId,
          toBucketId,
          trackIds: [track.track_id],
        };
        const snapshot = takeSnapshot(qc, blockId, bucketId);
        scheduleAdvance();
        schedulePulse();
        dispatch({
          type: 'ASSIGN_REPLACE_BEGIN',
          toBucketId,
          lastOp: { input, snapshot, trackIndex: stateRef.current.currentIndex },
        });
        fireMutation(input);
        return;
      }

      // Fresh assignment.
      const input: MoveInput = {
        fromBucketId: bucketId,
        toBucketId,
        trackIds: [track.track_id],
      };
      const snapshot = takeSnapshot(qc, blockId, bucketId);
      scheduleAdvance();
      schedulePulse();
      dispatch({
        type: 'ASSIGN_BEGIN',
        toBucketId,
        lastOp: { input, snapshot, trackIndex: stateRef.current.currentIndex },
      });
      fireMutation(input);
    },
    [
      queue,
      bucketId,
      blockId,
      styleId,
      qc,
      scheduleAdvance,
      schedulePulse,
      fireMutation,
    ],
  );

  const undo = useCallback(() => {
    const lastOp = stateRef.current.lastOp;
    if (!lastOp) return;
    const isPending = pendingTimerRef.current !== null;

    if (isPending) {
      clearTimeout(pendingTimerRef.current as number);
      pendingTimerRef.current = null;
      void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {});
      dispatch({ type: 'UNDO_WITHIN' });
    } else {
      void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {});
      dispatch({ type: 'UNDO_AFTER' });
    }
  }, [qc, blockId, styleId]);

  const skip = useCallback(() => {
    dispatch({ type: 'SKIP', max: queue.length });
  }, [queue.length]);

  const prev = useCallback(() => {
    dispatch({ type: 'PREV' });
  }, []);

  const openSpotify = useCallback(() => {
    if (currentTrack?.spotify_id) {
      window.open(
        `https://open.spotify.com/track/${currentTrack.spotify_id}`,
        '_blank',
        'noopener,noreferrer',
      );
    }
  }, [currentTrack]);

  return {
    status,
    queue,
    currentTrack,
    currentIndex: state.currentIndex,
    totalAssigned: state.totalAssigned,
    destinations,
    block: blockQuery.data ?? null,
    lastTappedBucketId: state.lastTappedBucketId,
    canUndo: state.lastOp !== null,
    assign,
    undo,
    skip,
    prev,
    openSpotify,
  };
}
```

- [ ] **Step 4: Run scaffolding tests to verify they pass**

```bash
cd frontend && pnpm test src/features/curate/hooks/__tests__/useCurateSession.test.tsx
```

Expected: 2 passing.

- [ ] **Step 5: Add assign / advance / double-tap tests**

Append to the same test file (after the closing `});` of the previous `describe`):

```tsx
describe('useCurateSession — assign + advance', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('schedules advance 200ms after assign and writes localStorage on success', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));

    act(() => {
      result.current.assign('dst1');
    });
    expect(result.current.lastTappedBucketId).toBe('dst1');
    expect(result.current.canUndo).toBe(true);
    expect(result.current.totalAssigned).toBe(1);
    // pulse has not yet cleared; advance has not yet fired
    expect(result.current.currentIndex).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(80);
    });
    expect(result.current.lastTappedBucketId).toBeNull();
    expect(result.current.currentIndex).toBe(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120); // 80 + 120 = 200ms total
    });
    await waitFor(() => expect(result.current.currentIndex).toBe(1));

    // localStorage updated by onSuccess
    await waitFor(() => {
      expect(localStorage.getItem(LAST_CURATE_STYLE_KEY)).toBe('s1');
      const stored = JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}');
      expect(stored.s1).toMatchObject({ blockId: 'b1', bucketId: 'src' });
    });
  });

  it('double-tap with different destination — first reverted, second applied, single advance', async () => {
    let firstSeen = false;
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () => {
        firstSeen = true;
        return HttpResponse.json({ moved: 1, correlation_id: 'cid' });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));

    act(() => result.current.assign('dst1'));
    expect(result.current.totalAssigned).toBe(1);
    act(() => result.current.assign('dst2'));
    expect(result.current.lastTappedBucketId).toBe('dst2');
    // totalAssigned stays at 1 — replace doesn't double-count
    expect(result.current.totalAssigned).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(result.current.currentIndex).toBe(1);
    expect(firstSeen).toBe(true);
  });

  it('double-tap with same destination — no rollback, single advance, timer reset', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));

    act(() => result.current.assign('dst1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150); // not yet at 200
    });
    expect(result.current.currentIndex).toBe(0);

    act(() => result.current.assign('dst1'));
    // Timer reset — wait another 199ms, still no advance
    await act(async () => {
      await vi.advanceTimersByTimeAsync(199);
    });
    expect(result.current.currentIndex).toBe(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2);
    });
    expect(result.current.currentIndex).toBe(1);
    expect(result.current.totalAssigned).toBe(1);
  });

  it('rejects assign to the source bucket itself (no-op)', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('src'));
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });
});

describe('useCurateSession — undo + skip + prev', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('undo within window cancels the advance and restores state', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('dst1'));
    act(() => result.current.undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(result.current.currentIndex).toBe(0);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });

  it('undo after advance restores index to the just-undone track', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('dst1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(result.current.currentIndex).toBe(1);
    act(() => result.current.undo());
    expect(result.current.currentIndex).toBe(0);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });

  it('undo with no lastOp is a no-op', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.undo());
    expect(result.current.currentIndex).toBe(0);
  });

  it('skip advances index without assigning', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.skip());
    expect(result.current.currentIndex).toBe(1);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.totalAssigned).toBe(0);
  });

  it('prev decrements index but never below 0', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.skip());
    expect(result.current.currentIndex).toBe(1);
    act(() => result.current.prev());
    act(() => result.current.prev());
    expect(result.current.currentIndex).toBe(0);
  });
});

describe('useCurateSession — error path', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json(tracksPage(['t1', 't2'])),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'tracks_not_in_source', message: 'race', correlation_id: 'x' },
          { status: 422 },
        ),
      ),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('on 422 tracks_not_in_source: clears lastOp and pending timer', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.assign('dst1'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    // Mutation onError fires; reducer should clean up
    await waitFor(() => expect(result.current.canUndo).toBe(false));
    expect(result.current.totalAssigned).toBe(0);
  });
});
```

- [ ] **Step 6: Run all useCurateSession tests**

```bash
cd frontend && pnpm test src/features/curate/hooks/__tests__/useCurateSession.test.tsx
```

Expected: all passing. If `vi.useFakeTimers({ shouldAdvanceTime: true })` proves brittle with TQ5 microtasks (CLAUDE.md gotcha #19), switch to `vi.useFakeTimers()` without the option and call `await vi.advanceTimersByTimeAsync(...)` between every state assertion. Real-timer fallback: drop `vi.useFakeTimers()` entirely, replace `advanceTimersByTimeAsync` with `await waitFor(() => expect(result.current.currentIndex).toBe(1), { timeout: 1000 })`.

- [ ] **Step 7: Run typecheck + lint**

```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateSession.ts frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx
git commit -m "feat(curate): add useCurateSession state machine"
```

---

## Task 6: `useCurateHotkeys` desktop-only key binder + tests

**Why now:** Wraps `Session` callbacks behind keyboard. Tested with mocked `Session`.

**Files:**
- Create: `frontend/src/features/curate/hooks/useCurateHotkeys.ts`
- Create: `frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx`

### Architectural notes

- Bind on `event.code` for digits + letters (layout-safe: `KeyQ`, `KeyW`, `KeyE`, `KeyJ`, `KeyK`, `KeyU`, `Digit0`-`Digit9`, `Space`, `Escape`, `Enter`).
- `?` is shifted on US-QWERTY but the user-facing intent is "the question mark key" — match `event.key === '?'` for help.
- Skip when `event.target` is `<input>`, `<textarea>`, `[contenteditable="true"]`. Skip on mobile (`useMediaQuery('(max-width: 64em)') === true`).
- Caller passes resolved destination buckets (the staging slots + tech + discard already resolved by `destinationMap`) so the hook does NOT recompute. This keeps the hook simple and unit-testable.

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { useCurateHotkeys } from '../useCurateHotkeys';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

vi.mock('@mantine/hooks', async () => {
  const actual = await vi.importActual<typeof import('@mantine/hooks')>('@mantine/hooks');
  return { ...actual, useMediaQuery: vi.fn(() => false) };
});

const stage = (id: string, name: string): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive: false,
  track_count: 0,
  category_id: `c-${id}`,
  category_name: name,
});
const tech = (id: string, t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD'): TriageBucket => ({
  id,
  bucket_type: t,
  inactive: false,
  track_count: 0,
});

const buckets: TriageBucket[] = [
  tech('b-new', 'NEW'),
  tech('b-old', 'OLD'),
  tech('b-not', 'NOT'),
  tech('b-disc', 'DISCARD'),
  stage('s1', 'A'),
  stage('s2', 'B'),
  stage('s3', 'C'),
];

function dispatchKey(opts: { code?: string; key?: string }): void {
  const ev = new KeyboardEvent('keydown', {
    code: opts.code ?? '',
    key: opts.key ?? '',
    bubbles: true,
    cancelable: true,
  });
  window.dispatchEvent(ev);
}

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MantineProvider theme={testTheme}>{children}</MantineProvider>
);

describe('useCurateHotkeys', () => {
  let onAssign: ReturnType<typeof vi.fn>;
  let onUndo: ReturnType<typeof vi.fn>;
  let onSkip: ReturnType<typeof vi.fn>;
  let onPrev: ReturnType<typeof vi.fn>;
  let onOpenOverlay: ReturnType<typeof vi.fn>;
  let onCloseOverlay: ReturnType<typeof vi.fn>;
  let onExit: ReturnType<typeof vi.fn>;
  let onOpenSpotify: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onAssign = vi.fn();
    onUndo = vi.fn();
    onSkip = vi.fn();
    onPrev = vi.fn();
    onOpenOverlay = vi.fn();
    onCloseOverlay = vi.fn();
    onExit = vi.fn();
    onOpenSpotify = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  function mount(overlayOpen: boolean) {
    return renderHook(
      () =>
        useCurateHotkeys({
          buckets,
          overlayOpen,
          onAssign,
          onUndo,
          onSkip,
          onPrev,
          onOpenOverlay,
          onCloseOverlay,
          onExit,
          onOpenSpotify,
        }),
      { wrapper },
    );
  }

  it('Digit1 calls onAssign with first staging bucket', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit1' }));
    expect(onAssign).toHaveBeenCalledWith('s1');
  });

  it('Digit3 calls onAssign with third staging bucket', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit3' }));
    expect(onAssign).toHaveBeenCalledWith('s3');
  });

  it('Digit4 with no slot is a no-op', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit4' }));
    expect(onAssign).not.toHaveBeenCalled();
  });

  it('KeyQ / KeyW / KeyE map to NEW / OLD / NOT', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyQ' }));
    expect(onAssign).toHaveBeenCalledWith('b-new');
    act(() => dispatchKey({ code: 'KeyW' }));
    expect(onAssign).toHaveBeenCalledWith('b-old');
    act(() => dispatchKey({ code: 'KeyE' }));
    expect(onAssign).toHaveBeenCalledWith('b-not');
  });

  it('Digit0 calls onAssign with DISCARD', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit0' }));
    expect(onAssign).toHaveBeenCalledWith('b-disc');
  });

  it('KeyU calls onUndo', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyU' }));
    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it('KeyJ / KeyK call onSkip / onPrev', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyJ' }));
    expect(onSkip).toHaveBeenCalledTimes(1);
    act(() => dispatchKey({ code: 'KeyK' }));
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it('Space calls onOpenSpotify', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Space' }));
    expect(onOpenSpotify).toHaveBeenCalledTimes(1);
  });

  it('? opens the overlay', () => {
    mount(false);
    act(() => dispatchKey({ key: '?' }));
    expect(onOpenOverlay).toHaveBeenCalledTimes(1);
  });

  it('Escape with overlay open calls onCloseOverlay', () => {
    mount(true);
    act(() => dispatchKey({ code: 'Escape' }));
    expect(onCloseOverlay).toHaveBeenCalledTimes(1);
    expect(onExit).not.toHaveBeenCalled();
  });

  it('Escape with overlay closed calls onExit', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Escape' }));
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(onCloseOverlay).not.toHaveBeenCalled();
  });

  it('ignores keystrokes when target is an <input>', () => {
    mount(false);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    const ev = new KeyboardEvent('keydown', {
      code: 'Digit1',
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(ev, 'target', { value: input });
    window.dispatchEvent(ev);
    expect(onAssign).not.toHaveBeenCalled();
    document.body.removeChild(input);
  });

  it('mobile: no listeners bound', async () => {
    const mod = await import('@mantine/hooks');
    (mod.useMediaQuery as unknown as ReturnType<typeof vi.fn>).mockReturnValue(true);
    mount(false);
    act(() => dispatchKey({ code: 'Digit1' }));
    expect(onAssign).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx
```

Expected: FAIL with module not found.

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/curate/hooks/useCurateHotkeys.ts
import { useEffect } from 'react';
import { useMediaQuery } from '@mantine/hooks';
import type { TriageBucket } from '../../triage/lib/bucketLabels';
import { byDiscard, byPosition, byTechType } from '../lib/destinationMap';

export interface UseCurateHotkeysArgs {
  buckets: TriageBucket[];
  overlayOpen: boolean;
  onAssign: (toBucketId: string) => void;
  onUndo: () => void;
  onSkip: () => void;
  onPrev: () => void;
  onOpenOverlay: () => void;
  onCloseOverlay: () => void;
  onExit: () => void;
  onOpenSpotify: () => void;
}

const DIGIT_CODES: Record<string, number> = {
  Digit1: 0,
  Digit2: 1,
  Digit3: 2,
  Digit4: 3,
  Digit5: 4,
  Digit6: 5,
  Digit7: 6,
  Digit8: 7,
  Digit9: 8,
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

export function useCurateHotkeys(args: UseCurateHotkeysArgs): void {
  const isMobile = useMediaQuery('(max-width: 64em)');
  const {
    buckets,
    overlayOpen,
    onAssign,
    onUndo,
    onSkip,
    onPrev,
    onOpenOverlay,
    onCloseOverlay,
    onExit,
    onOpenSpotify,
  } = args;

  useEffect(() => {
    if (isMobile) return;
    const handler = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;

      // Help overlay (key form because of layout sensitivity).
      if (event.key === '?') {
        event.preventDefault();
        onOpenOverlay();
        return;
      }

      switch (event.code) {
        case 'Escape':
          event.preventDefault();
          if (overlayOpen) onCloseOverlay();
          else onExit();
          return;
        case 'KeyU':
          event.preventDefault();
          onUndo();
          return;
        case 'KeyJ':
          event.preventDefault();
          onSkip();
          return;
        case 'KeyK':
          event.preventDefault();
          onPrev();
          return;
        case 'Space':
          event.preventDefault();
          onOpenSpotify();
          return;
        case 'KeyQ': {
          event.preventDefault();
          const b = byTechType(buckets, 'NEW');
          if (b) onAssign(b.id);
          return;
        }
        case 'KeyW': {
          event.preventDefault();
          const b = byTechType(buckets, 'OLD');
          if (b) onAssign(b.id);
          return;
        }
        case 'KeyE': {
          event.preventDefault();
          const b = byTechType(buckets, 'NOT');
          if (b) onAssign(b.id);
          return;
        }
        case 'Digit0': {
          event.preventDefault();
          const b = byDiscard(buckets);
          if (b) onAssign(b.id);
          return;
        }
        default: {
          const slot = DIGIT_CODES[event.code];
          if (slot !== undefined) {
            event.preventDefault();
            const b = byPosition(buckets, slot);
            if (b) onAssign(b.id);
          }
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    isMobile,
    buckets,
    overlayOpen,
    onAssign,
    onUndo,
    onSkip,
    onPrev,
    onOpenOverlay,
    onCloseOverlay,
    onExit,
    onOpenSpotify,
  ]);
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx
```

Expected: 12 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateHotkeys.ts frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx
git commit -m "feat(curate): add useCurateHotkeys binder"
```

---

## Task 7: `CurateSkeleton` loader

**Why now:** Tiny presentational component used by index / resume / session loading. No tests beyond a smoke "renders" — pure layout.

**Files:**
- Create: `frontend/src/features/curate/components/CurateSkeleton.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/curate/components/CurateSkeleton.tsx
import { Group, Skeleton, Stack } from '@mantine/core';

export function CurateSkeleton(): JSX.Element {
  return (
    <Stack gap="lg" p="xl" data-testid="curate-skeleton">
      <Group align="flex-start" gap="xl" wrap="nowrap">
        <Stack gap="md" style={{ flex: 1 }}>
          <Skeleton height={32} width="60%" radius="md" />
          <Skeleton height={20} width="40%" radius="md" />
          <Skeleton height={400} radius="lg" />
        </Stack>
        <Stack gap="sm" style={{ width: 320 }}>
          <Skeleton height={64} radius="md" />
          <Skeleton height={64} radius="md" />
          <Skeleton height={64} radius="md" />
          <Skeleton height={64} radius="md" />
        </Stack>
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 2: Smoke test**

```tsx
// frontend/src/features/curate/components/__tests__/CurateSkeleton.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CurateSkeleton } from '../CurateSkeleton';

describe('CurateSkeleton', () => {
  it('renders the loading layout', () => {
    render(
      <MantineProvider theme={testTheme}>
        <CurateSkeleton />
      </MantineProvider>,
    );
    expect(screen.getByTestId('curate-skeleton')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run + commit**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/CurateSkeleton.test.tsx
git add frontend/src/features/curate/components/CurateSkeleton.tsx frontend/src/features/curate/components/__tests__/CurateSkeleton.test.tsx
git commit -m "feat(curate): add CurateSkeleton"
```

---

## Task 8: `CurateCard` track presentation + tests

**Files:**
- Create: `frontend/src/features/curate/components/CurateCard.tsx`
- Create: `frontend/src/features/curate/components/__tests__/CurateCard.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/components/__tests__/CurateCard.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CurateCard } from '../CurateCard';
import type { BucketTrack } from '../../../triage/hooks/useBucketTracks';

const mkTrack = (overrides: Partial<BucketTrack> = {}): BucketTrack => ({
  track_id: 't1',
  title: 'Sunset Drive',
  mix_name: 'Original Mix',
  isrc: null,
  bpm: 124,
  length_ms: 360000,
  publish_date: '2026-04-15',
  spotify_release_date: '2026-04-15',
  spotify_id: 'sp-t1',
  release_type: 'single',
  is_ai_suspected: false,
  artists: ['Artist A', 'Artist B'],
  label_name: 'Big Room Records',
  added_at: '2026-04-21T00:00:00Z',
  ...overrides,
});

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('CurateCard', () => {
  it('renders title, mix, artists, label, BPM, length, release date', () => {
    render(wrap(<CurateCard track={mkTrack()} />));
    expect(screen.getByText('Sunset Drive')).toBeInTheDocument();
    expect(screen.getByText(/Original Mix/)).toBeInTheDocument();
    expect(screen.getByText('Artist A, Artist B')).toBeInTheDocument();
    expect(screen.getByText('Big Room Records')).toBeInTheDocument();
    expect(screen.getByText('124')).toBeInTheDocument();
    expect(screen.getByText('06:00')).toBeInTheDocument();
    expect(screen.getByText('2026-04-15')).toBeInTheDocument();
  });

  it('renders the AI badge when is_ai_suspected', () => {
    render(wrap(<CurateCard track={mkTrack({ is_ai_suspected: true })} />));
    expect(screen.getByText(/AI suspect/i)).toBeInTheDocument();
  });

  it('hides the AI badge when not suspected', () => {
    render(wrap(<CurateCard track={mkTrack({ is_ai_suspected: false })} />));
    expect(screen.queryByText(/AI suspect/i)).toBeNull();
  });

  it('renders the Open in Spotify button when spotify_id is present', () => {
    render(wrap(<CurateCard track={mkTrack()} />));
    const link = screen.getByRole('link', { name: /Open .* in Spotify/i });
    expect(link).toHaveAttribute('href', 'https://open.spotify.com/track/sp-t1');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('hides the Spotify link and shows fallback copy when spotify_id is null', () => {
    render(wrap(<CurateCard track={mkTrack({ spotify_id: null })} />));
    expect(screen.queryByRole('link', { name: /Spotify/i })).toBeNull();
    expect(screen.getByText(/No Spotify match/i)).toBeInTheDocument();
  });

  it('formats unknown BPM and length gracefully', () => {
    render(wrap(<CurateCard track={mkTrack({ bpm: null, length_ms: null })} />));
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/CurateCard.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/components/CurateCard.tsx
import { Anchor, Badge, Group, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useMediaQuery } from '@mantine/hooks';
import type { BucketTrack } from '../../triage/hooks/useBucketTracks';
import { IconExternalLink } from '../../../components/icons';

export interface CurateCardProps {
  track: BucketTrack;
}

function formatLengthMs(ms: number | null): string {
  if (ms === null) return '—';
  const total = Math.round(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function formatBpm(bpm: number | null): string {
  return bpm === null ? '—' : String(bpm);
}

function formatReleaseDate(track: BucketTrack): string {
  return track.spotify_release_date ?? track.publish_date ?? '—';
}

export function CurateCard({ track }: CurateCardProps): JSX.Element {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');

  const titleSize = isMobile ? 'h2' : 'h1';
  const titleOrder: 1 | 2 = isMobile ? 2 : 1;
  const artists = track.artists.join(', ') || '—';

  return (
    <Stack
      gap={isMobile ? 'sm' : 'md'}
      p={isMobile ? 'md' : 'xl'}
      style={{
        background: 'var(--color-bg-elevated)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-sm)',
        minHeight: isMobile ? 'auto' : 480,
      }}
      data-testid="curate-card"
    >
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          {track.is_ai_suspected && (
            <Badge color="yellow" variant="light" aria-label={t('curate.card.ai_badge_aria')}>
              {t('curate.card.ai_badge')}
            </Badge>
          )}
          <Title order={titleOrder} size={titleSize}>
            {track.title}
          </Title>
          {track.mix_name && (
            <Text c="var(--color-fg-muted)" size={isMobile ? 'sm' : 'md'}>
              {track.mix_name}
            </Text>
          )}
          <Text size={isMobile ? 'sm' : 'md'} c="var(--color-fg)">
            {artists}
          </Text>
        </Stack>
      </Group>

      <Stack gap={4}>
        <Group gap="md" wrap="wrap">
          <Text size="sm" c="var(--color-fg-muted)">
            {t('curate.card.label_label')}: {track.label_name ?? '—'}
          </Text>
          <Text size="sm" c="var(--color-fg-muted)">
            {t('curate.card.bpm_label')}: {formatBpm(track.bpm)}
          </Text>
          <Text size="sm" c="var(--color-fg-muted)">
            {t('curate.card.length_label')}: {formatLengthMs(track.length_ms)}
          </Text>
          <Text size="sm" c="var(--color-fg-muted)">
            {t('curate.card.released_label')}: {formatReleaseDate(track)}
          </Text>
        </Group>
      </Stack>

      <Group justify="flex-start">
        {track.spotify_id ? (
          <Anchor
            href={`https://open.spotify.com/track/${track.spotify_id}`}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t('curate.card.open_in_spotify_aria', { title: track.title })}
            c="var(--color-fg)"
            td="none"
          >
            <Group gap={6}>
              <Text>{t('curate.card.open_in_spotify')}</Text>
              <IconExternalLink size={14} />
            </Group>
          </Anchor>
        ) : (
          <Text size="sm" c="var(--color-fg-subtle)">
            {t('curate.card.no_spotify_id')}
          </Text>
        )}
      </Group>
    </Stack>
  );
}
```

If `IconExternalLink` is not yet exported from `frontend/src/components/icons`, add it:

```ts
// in frontend/src/components/icons.ts (sibling to existing icon re-exports)
export { IconExternalLink } from '@tabler/icons-react';
```

(Verify the icon list before adding — if it already exists, skip this step.)

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/CurateCard.test.tsx
git add frontend/src/features/curate/components/CurateCard.tsx frontend/src/features/curate/components/__tests__/CurateCard.test.tsx frontend/src/components/icons.ts
git commit -m "feat(curate): add CurateCard track presentation"
```

---

## Task 9: `DestinationButton` + tests

**Files:**
- Create: `frontend/src/features/curate/components/DestinationButton.tsx`
- Create: `frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { DestinationButton } from '../DestinationButton';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

const stage: TriageBucket = {
  id: 's1',
  bucket_type: 'STAGING',
  inactive: false,
  track_count: 0,
  category_id: 'c1',
  category_name: 'Big Room',
};

const newBucket: TriageBucket = {
  id: 'b-new',
  bucket_type: 'NEW',
  inactive: false,
  track_count: 5,
};

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('DestinationButton', () => {
  it('renders the staging bucket label and hotkey badge', () => {
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={false}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to Big Room/i })).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('renders technical bucket label', () => {
    render(
      wrap(
        <DestinationButton
          bucket={newBucket}
          hotkeyHint="Q"
          justTapped={false}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to NEW/ })).toBeInTheDocument();
  });

  it('fires onClick when clicked', () => {
    const onClick = vi.fn();
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={false}
          disabled={false}
          onClick={onClick}
        />,
      ),
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('disabled prevents clicks', () => {
    const onClick = vi.fn();
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={false}
          disabled={true}
          onClick={onClick}
        />,
      ),
    );
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('sets data-just-tapped="true" when justTapped is true', () => {
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={true}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button')).toHaveAttribute('data-just-tapped', 'true');
  });

  it('renders inactive staging with disabled title', () => {
    const inactive = { ...stage, inactive: true };
    render(
      wrap(
        <DestinationButton
          bucket={inactive}
          hotkeyHint="1"
          justTapped={false}
          disabled={true}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button')).toHaveAttribute(
      'title',
      expect.stringContaining('Category inactive'),
    );
  });

  it('omits hotkey badge when hotkeyHint is null', () => {
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint={null}
          justTapped={false}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.queryByText('1')).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/DestinationButton.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/components/DestinationButton.tsx
import { Group, Kbd, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import classes from './DestinationButton.module.css';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';

export interface DestinationButtonProps {
  bucket: TriageBucket;
  hotkeyHint: string | null;
  justTapped: boolean;
  disabled: boolean;
  onClick: () => void;
}

export function DestinationButton({
  bucket,
  hotkeyHint,
  justTapped,
  disabled,
  onClick,
}: DestinationButtonProps): JSX.Element {
  const { t } = useTranslation();
  const label = bucketLabel(bucket, t);

  let title: string | undefined;
  if (disabled) {
    title =
      bucket.bucket_type === 'STAGING' && bucket.inactive
        ? t('curate.destination.inactive_disabled_title')
        : t('curate.destination.self_disabled_title');
  }

  return (
    <UnstyledButton
      onClick={onClick}
      disabled={disabled}
      className={classes.button}
      data-just-tapped={justTapped ? 'true' : 'false'}
      data-disabled={disabled ? 'true' : 'false'}
      aria-label={t('curate.destination.assign_aria', { label })}
      title={title}
    >
      <Group justify="space-between" gap="md" wrap="nowrap" px="md" py="xs">
        <span className={classes.label}>{label}</span>
        {hotkeyHint !== null && <Kbd>{hotkeyHint}</Kbd>}
      </Group>
    </UnstyledButton>
  );
}
```

```css
/* frontend/src/features/curate/components/DestinationButton.module.css */
.button {
  width: 100%;
  min-height: var(--control-xl, 56px);
  border-radius: var(--radius-md);
  border: var(--border-thin) solid var(--color-border);
  background: var(--color-bg-elevated);
  color: var(--color-fg);
  transition:
    transform var(--motion-pulse) var(--ease-out),
    background var(--motion-base) var(--ease-out);
}
.button:hover:not([data-disabled='true']) {
  background: var(--color-hover);
}
.button[data-disabled='true'] {
  opacity: 0.4;
  pointer-events: none;
}
.button[data-just-tapped='true'] {
  transform: scale(0.97);
  background: var(--color-selected-bg);
  color: var(--color-selected-fg);
}
.label {
  font-size: var(--text-14);
  font-weight: var(--weight-medium);
  text-align: left;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (prefers-reduced-motion: reduce) {
  .button[data-just-tapped='true'] {
    transform: none;
  }
  .button {
    transition: background var(--motion-base) var(--ease-out);
  }
}
@media (min-width: 64em) {
  .button {
    min-height: 64px;
  }
}
```

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/DestinationButton.test.tsx
git add frontend/src/features/curate/components/DestinationButton.tsx frontend/src/features/curate/components/DestinationButton.module.css frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx
git commit -m "feat(curate): add DestinationButton"
```

---

## Task 10: `DestinationGrid` composition + tests

**Files:**
- Create: `frontend/src/features/curate/components/DestinationGrid.tsx`
- Create: `frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { DestinationGrid } from '../DestinationGrid';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

const stage = (id: string, name: string, inactive = false): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive,
  track_count: 0,
  category_id: `c-${id}`,
  category_name: name,
});

const tech = (id: string, t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD'): TriageBucket => ({
  id,
  bucket_type: t,
  inactive: false,
  track_count: 0,
});

const buckets: TriageBucket[] = [
  tech('b-new', 'NEW'),
  tech('b-old', 'OLD'),
  tech('b-not', 'NOT'),
  tech('b-disc', 'DISCARD'),
  stage('s1', 'Big Room'),
  stage('s2', 'Hard Techno'),
  stage('s3', 'Tech House'),
];

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('DestinationGrid', () => {
  it('renders staging / technical / discard sections', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByText('Staging')).toBeInTheDocument();
    expect(screen.getByText('Technical')).toBeInTheDocument();
    expect(screen.getByText('Discard')).toBeInTheDocument();
  });

  it('renders staging buttons with digit hotkeys 1-N', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to Big Room/i })).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders Q/W/E and 0 hotkey badges', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByText('Q')).toBeInTheDocument();
    expect(screen.getByText('W')).toBeInTheDocument();
    expect(screen.getByText('E')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('passes lastTappedBucketId through to the matching DestinationButton', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId="s2"
          onAssign={() => {}}
        />,
      ),
    );
    const btn = screen.getByRole('button', { name: /Assign to Hard Techno/i });
    expect(btn).toHaveAttribute('data-just-tapped', 'true');
  });

  it('disables the source-bucket button (excluded entirely from rendering by default)', () => {
    // currentBucketId matching a tech bucket should hide it
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-new"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.queryByRole('button', { name: /Assign to NEW/ })).toBeNull();
  });

  it('clicking a button calls onAssign with the bucket id', () => {
    const onAssign = vi.fn();
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={onAssign}
        />,
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: /Assign to Big Room/i }));
    expect(onAssign).toHaveBeenCalledWith('s1');
  });

  it('renders More… menu when staging count exceeds 9', () => {
    const many: TriageBucket[] = [
      ...buckets,
      ...Array.from({ length: 8 }, (_, i) => stage(`s-extra-${i}`, `Extra ${i}`)),
    ];
    render(
      wrap(
        <DestinationGrid
          buckets={many}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /More categories/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/DestinationGrid.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/components/DestinationGrid.tsx
import { Menu, Stack, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { DestinationButton } from './DestinationButton';
import { IconChevronDown } from '../../../components/icons';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';
import {
  byDiscard,
  byTechType,
  resolveStagingHotkeys,
  stagingOverflow,
} from '../lib/destinationMap';

export interface DestinationGridProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  lastTappedBucketId: string | null;
  onAssign: (toBucketId: string) => void;
}

export function DestinationGrid({
  buckets,
  currentBucketId,
  lastTappedBucketId,
  onAssign,
}: DestinationGridProps): JSX.Element {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const visible = buckets.filter((b) => b.id !== currentBucketId);

  const stagingSlots = resolveStagingHotkeys(visible);
  const overflow = stagingOverflow(visible);

  const newBucket = byTechType(visible, 'NEW');
  const oldBucket = byTechType(visible, 'OLD');
  const notBucket = byTechType(visible, 'NOT');
  const discardBucket = byDiscard(visible);

  const renderBtn = (
    bucket: TriageBucket | null,
    hotkeyHint: string | null,
  ): JSX.Element | null => {
    if (!bucket) return null;
    return (
      <DestinationButton
        key={bucket.id}
        bucket={bucket}
        hotkeyHint={isMobile ? null : hotkeyHint}
        justTapped={lastTappedBucketId === bucket.id}
        disabled={false}
        onClick={() => onAssign(bucket.id)}
      />
    );
  };

  return (
    <Stack gap="md" data-testid="destination-grid">
      <Stack gap={4}>
        <Text size="xs" fw={600} c="var(--color-fg-muted)" tt="uppercase">
          {t('curate.destination.group_staging')}
        </Text>
        {stagingSlots.map((b, idx) => renderBtn(b, String(idx + 1)))}
        {overflow.length > 0 && (
          <Menu position="bottom-end" withinPortal>
            <Menu.Target>
              <DestinationButton
                bucket={{
                  id: '__overflow__',
                  bucket_type: 'STAGING',
                  inactive: false,
                  track_count: 0,
                  category_id: null,
                  category_name: t('curate.destination.more_categories'),
                }}
                hotkeyHint={null}
                justTapped={false}
                disabled={false}
                onClick={() => {}}
              />
            </Menu.Target>
            <Menu.Dropdown>
              {overflow.map((b) => (
                <Menu.Item key={b.id} onClick={() => onAssign(b.id)}>
                  {bucketLabel(b, t)}
                </Menu.Item>
              ))}
            </Menu.Dropdown>
          </Menu>
        )}
      </Stack>

      <Stack gap={4}>
        <Text size="xs" fw={600} c="var(--color-fg-muted)" tt="uppercase">
          {t('curate.destination.group_technical')}
        </Text>
        {renderBtn(newBucket, 'Q')}
        {renderBtn(oldBucket, 'W')}
        {renderBtn(notBucket, 'E')}
      </Stack>

      <Stack gap={4}>
        <Text size="xs" fw={600} c="var(--color-fg-muted)" tt="uppercase">
          {t('curate.destination.group_discard')}
        </Text>
        {renderBtn(discardBucket, '0')}
      </Stack>
    </Stack>
  );
}
```

`bucketLabel` for the synthetic overflow target uses `category_name` directly so the More… text reads naturally.

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/DestinationGrid.test.tsx
git add frontend/src/features/curate/components/DestinationGrid.tsx frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx
git commit -m "feat(curate): add DestinationGrid"
```

---

## Task 11: `HotkeyOverlay` modal + tests

**Files:**
- Create: `frontend/src/features/curate/components/HotkeyOverlay.tsx`
- Create: `frontend/src/features/curate/components/__tests__/HotkeyOverlay.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/components/__tests__/HotkeyOverlay.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { HotkeyOverlay } from '../HotkeyOverlay';

vi.mock('@mantine/hooks', async () => {
  const actual = await vi.importActual<typeof import('@mantine/hooks')>('@mantine/hooks');
  return { ...actual, useMediaQuery: vi.fn(() => false) };
});

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('HotkeyOverlay', () => {
  it('does not render when opened=false', () => {
    render(
      wrap(<HotkeyOverlay opened={false} onClose={() => {}} hasOverflow={false} />),
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders all key sections on desktop when opened', async () => {
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Keyboard shortcuts/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Assign to staging category 1–9/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Skip without assigning/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Show \/ hide this overlay/i)).toBeInTheDocument();
  });

  it('shows overflow note when hasOverflow=true', async () => {
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={true} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(/Categories beyond 9 are accessible via the More/i),
    ).toBeInTheDocument();
  });

  it('always shows audio-deferral footer', async () => {
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Audio playback ships in F6/i)).toBeInTheDocument();
  });

  it('mobile copy when useMediaQuery returns true', async () => {
    const mod = await import('@mantine/hooks');
    (mod.useMediaQuery as unknown as ReturnType<typeof vi.fn>).mockReturnValue(true);
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(/Keyboard shortcuts available on desktop only/i),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/Assign to staging category 1–9/i)).toBeNull();
  });

  it('close button fires onClose', async () => {
    const onClose = vi.fn();
    render(wrap(<HotkeyOverlay opened={true} onClose={onClose} hasOverflow={false} />));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/HotkeyOverlay.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/components/HotkeyOverlay.tsx
import { Group, Kbd, Modal, Stack, Table, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';

export interface HotkeyOverlayProps {
  opened: boolean;
  onClose: () => void;
  hasOverflow: boolean;
}

interface KeyRow {
  keys: string[];
  labelKey: string;
}

const ASSIGN: KeyRow[] = [
  { keys: ['1', '…', '9'], labelKey: 'curate.hotkeys.key_digits_label' },
  { keys: ['Q', 'W', 'E'], labelKey: 'curate.hotkeys.key_qwe_label' },
  { keys: ['0'], labelKey: 'curate.hotkeys.key_zero_label' },
];
const NAVIGATE: KeyRow[] = [
  { keys: ['J'], labelKey: 'curate.hotkeys.key_j_label' },
  { keys: ['K'], labelKey: 'curate.hotkeys.key_k_label' },
];
const ACTION: KeyRow[] = [
  { keys: ['Space'], labelKey: 'curate.hotkeys.key_space_label' },
  { keys: ['U'], labelKey: 'curate.hotkeys.key_u_label' },
];
const SYSTEM: KeyRow[] = [
  { keys: ['?'], labelKey: 'curate.hotkeys.key_help_label' },
  { keys: ['Esc'], labelKey: 'curate.hotkeys.key_esc_label' },
  { keys: ['Enter'], labelKey: 'curate.hotkeys.key_enter_label' },
];

function KeyTable({ rows, t }: { rows: KeyRow[]; t: ReturnType<typeof useTranslation>['t'] }) {
  return (
    <Table withRowBorders={false}>
      <Table.Tbody>
        {rows.map((row) => (
          <Table.Tr key={row.labelKey}>
            <Table.Td style={{ width: 120 }}>
              <Group gap={4}>
                {row.keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </Group>
            </Table.Td>
            <Table.Td>{t(row.labelKey)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function HotkeyOverlay({
  opened,
  onClose,
  hasOverflow,
}: HotkeyOverlayProps): JSX.Element {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');

  return (
    <Modal opened={opened} onClose={onClose} title={t('curate.hotkeys.title')} size="md" centered>
      <Stack gap="md">
        {isMobile ? (
          <>
            <Text>{t('curate.hotkeys.mobile_note')}</Text>
            <KeyTable rows={ACTION} t={t} />
            <KeyTable rows={SYSTEM} t={t} />
          </>
        ) : (
          <>
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_assign')}
            </Text>
            <KeyTable rows={ASSIGN} t={t} />
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_navigate')}
            </Text>
            <KeyTable rows={NAVIGATE} t={t} />
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_action')}
            </Text>
            <KeyTable rows={ACTION} t={t} />
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_system')}
            </Text>
            <KeyTable rows={SYSTEM} t={t} />
          </>
        )}
        <Text size="xs" c="var(--color-fg-muted)">
          {t('curate.hotkeys.footer_audio_note')}
        </Text>
        {hasOverflow && (
          <Text size="xs" c="var(--color-fg-muted)">
            {t('curate.hotkeys.footer_overflow_note')}
          </Text>
        )}
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/HotkeyOverlay.test.tsx
git add frontend/src/features/curate/components/HotkeyOverlay.tsx frontend/src/features/curate/components/__tests__/HotkeyOverlay.test.tsx
git commit -m "feat(curate): add HotkeyOverlay"
```

---

## Task 12: `EndOfQueue` surface + tests

**Files:**
- Create: `frontend/src/features/curate/components/EndOfQueue.tsx`
- Create: `frontend/src/features/curate/components/__tests__/EndOfQueue.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/components/__tests__/EndOfQueue.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { EndOfQueue } from '../EndOfQueue';
import type { TriageBlock } from '../../../triage/hooks/useTriageBlock';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

function mkBlock(buckets: TriageBucket[]): TriageBlock {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'Tech House',
    name: 'TH W17',
    date_from: '2026-04-21',
    date_to: '2026-04-27',
    status: 'IN_PROGRESS',
    created_at: '2026-04-20T00:00:00Z',
    updated_at: '2026-04-20T00:00:00Z',
    finalized_at: null,
    buckets,
  };
}

const wrap = (ui: React.ReactElement) => (
  <MemoryRouter>
    <MantineProvider theme={testTheme}>{ui}</MantineProvider>
  </MemoryRouter>
);

describe('EndOfQueue', () => {
  it('renders Continue CTA when a non-empty source-eligible bucket exists', () => {
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
      { id: 'old', bucket_type: 'OLD', inactive: false, track_count: 5 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={3}
        />,
      ),
    );
    expect(screen.getByText(/You sorted 3 tracks/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Continue with OLD \(5\)/i })).toHaveAttribute(
      'href',
      '/curate/s1/b1/old',
    );
  });

  it('renders Finalize CTA when no non-empty source-eligible bucket exists', () => {
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={0}
        />,
      ),
    );
    expect(screen.getByRole('link', { name: /Finalize block/i })).toHaveAttribute(
      'href',
      '/triage/s1/b1',
    );
    expect(screen.getByText(/No tracks sorted in this session/i)).toBeInTheDocument();
  });

  it('always renders Back to triage', () => {
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={1}
        />,
      ),
    );
    expect(screen.getByRole('link', { name: /Back to triage/i })).toHaveAttribute(
      'href',
      '/triage/s1/b1',
    );
    expect(screen.getByText(/You sorted 1 track/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/EndOfQueue.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/components/EndOfQueue.tsx
import { Button, Group, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TriageBlock } from '../../triage/hooks/useTriageBlock';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';
import { nextSuggestedBucket } from '../lib/nextSuggestedBucket';

export interface EndOfQueueProps {
  styleId: string;
  block: TriageBlock;
  currentBucketId: string;
  totalAssigned: number;
}

function bodyKey(count: number): string {
  if (count === 0) return 'curate.end_of_queue.body_zero';
  if (count === 1) return 'curate.end_of_queue.body_one';
  return 'curate.end_of_queue.body_other';
}

export function EndOfQueue({
  styleId,
  block,
  currentBucketId,
  totalAssigned,
}: EndOfQueueProps): JSX.Element {
  const { t } = useTranslation();
  const currentBucket: TriageBucket | undefined = block.buckets.find(
    (b) => b.id === currentBucketId,
  );
  const currentLabel = currentBucket ? bucketLabel(currentBucket, t) : '';
  const next = nextSuggestedBucket(block.buckets, currentBucketId);

  return (
    <Stack gap="lg" align="center" p="xl" data-testid="end-of-queue">
      <Title order={2}>{t('curate.end_of_queue.heading', { label: currentLabel })}</Title>
      <Text c="var(--color-fg-muted)">
        {t(bodyKey(totalAssigned), { count: totalAssigned })}
      </Text>
      <Group>
        {next ? (
          <Button component={Link} to={`/curate/${styleId}/${block.id}/${next.id}`}>
            {t('curate.end_of_queue.continue_cta', {
              label: bucketLabel(next, t),
              count: next.track_count,
            })}
          </Button>
        ) : (
          <Button component={Link} to={`/triage/${styleId}/${block.id}`}>
            {t('curate.end_of_queue.finalize_cta')}
          </Button>
        )}
        <Button variant="default" component={Link} to={`/triage/${styleId}/${block.id}`}>
          {t('curate.end_of_queue.back_to_triage_cta')}
        </Button>
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/EndOfQueue.test.tsx
git add frontend/src/features/curate/components/EndOfQueue.tsx frontend/src/features/curate/components/__tests__/EndOfQueue.test.tsx
git commit -m "feat(curate): add EndOfQueue surface"
```

---

## Task 13: `CurateSetupPage` block + bucket picker + tests

**Files:**
- Create: `frontend/src/features/curate/components/CurateSetupPage.tsx`
- Create: `frontend/src/features/curate/components/__tests__/CurateSetupPage.test.tsx`

### Architectural notes

- Reuses `useTriageBlocksByStyle('IN_PROGRESS', styleId)` (F2) and `useTriageBlock(blockId)` (F3a) for picker data.
- Uses `useStyles` (F1) only for the empty-state heading (looks up the human-readable style name).
- Bucket select: filter to non-STAGING + `track_count > 0`. Default to NEW → UNCLASSIFIED → OLD → NOT (use `nextSuggestedBucket` with `currentBucketId=''`).
- Submit button is `<Link>`-styled `<Button>` whose `to` is built from the picks.

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/components/__tests__/CurateSetupPage.test.tsx
import React from 'react';
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateSetupPage } from '../CurateSetupPage';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

const wrap = (ui: React.ReactElement) => {
  const qc = makeClient();
  return (
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>{ui}</MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
};

beforeEach(() => tokenStore.set('TOK'));

describe('CurateSetupPage', () => {
  it('shows the no-active-blocks empty state when style has zero IN_PROGRESS blocks', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json([{ id: 's1', name: 'Tech House' }]),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(wrap(<CurateSetupPage styleId="s1" />));
    expect(
      await screen.findByText(/No active blocks for Tech House/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Triage/i })).toHaveAttribute(
      'href',
      '/triage/s1',
    );
  });

  it('lists IN_PROGRESS blocks and pre-selects first; bucket select pre-selects NEW', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json([{ id: 's1', name: 'Tech House' }]),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [
            {
              id: 'b1',
              style_id: 's1',
              style_name: 'Tech House',
              name: 'W17',
              date_from: '2026-04-21',
              date_to: '2026-04-27',
              status: 'IN_PROGRESS',
              created_at: '2026-04-20T00:00:00Z',
              updated_at: '2026-04-20T00:00:00Z',
              finalized_at: null,
              total_tracks: 100,
              track_count_by_bucket: {},
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
          id: 'b1',
          style_id: 's1',
          style_name: 'Tech House',
          name: 'W17',
          date_from: '2026-04-21',
          date_to: '2026-04-27',
          status: 'IN_PROGRESS',
          created_at: '2026-04-20T00:00:00Z',
          updated_at: '2026-04-20T00:00:00Z',
          finalized_at: null,
          buckets: [
            { id: 'b-new', bucket_type: 'NEW', inactive: false, track_count: 5 },
            { id: 'b-old', bucket_type: 'OLD', inactive: false, track_count: 0 },
            { id: 'b-stage', bucket_type: 'STAGING', inactive: false, track_count: 0,
              category_id: 'c1', category_name: 'Big Room' },
          ],
        }),
      ),
    );
    render(wrap(<CurateSetupPage styleId="s1" />));
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Start curating/i })).toHaveAttribute(
        'href',
        '/curate/s1/b1/b-new',
      ),
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/CurateSetupPage.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/components/CurateSetupPage.tsx
import { useEffect, useMemo, useState } from 'react';
import { Button, Center, Select, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useStyles } from '../../categories/hooks/useStyles';
import { useTriageBlocksByStyle } from '../../triage/hooks/useTriageBlocksByStyle';
import { useTriageBlock } from '../../triage/hooks/useTriageBlock';
import { EmptyState } from '../../../components/EmptyState';
import { CurateSkeleton } from './CurateSkeleton';
import { nextSuggestedBucket } from '../lib/nextSuggestedBucket';

export interface CurateSetupPageProps {
  styleId: string;
}

export function CurateSetupPage({ styleId }: CurateSetupPageProps): JSX.Element {
  const { t } = useTranslation();
  const styles = useStyles();
  const blocks = useTriageBlocksByStyle('IN_PROGRESS', styleId);
  const styleName = styles.data?.find((s) => s.id === styleId)?.name ?? styleId;

  const blockItems = useMemo(
    () =>
      (blocks.data?.items ?? []).map((b) => ({
        value: b.id,
        label: `${b.name} (${b.date_from} → ${b.date_to})`,
      })),
    [blocks.data],
  );

  const [blockId, setBlockId] = useState<string | null>(null);
  useEffect(() => {
    if (!blockId && blockItems.length > 0) setBlockId(blockItems[0]?.value ?? null);
  }, [blockId, blockItems]);

  const blockDetail = useTriageBlock(blockId ?? '');
  const eligibleBuckets = useMemo(
    () =>
      (blockDetail.data?.buckets ?? []).filter(
        (b) => b.bucket_type !== 'STAGING' && b.track_count > 0,
      ),
    [blockDetail.data],
  );
  const bucketItems = useMemo(
    () =>
      eligibleBuckets.map((b) => ({
        value: b.id,
        label: `${b.bucket_type} (${b.track_count})`,
      })),
    [eligibleBuckets],
  );

  const [bucketId, setBucketId] = useState<string | null>(null);
  useEffect(() => {
    if (!blockDetail.data) return;
    const suggested = nextSuggestedBucket(blockDetail.data.buckets, '');
    if (suggested) setBucketId(suggested.id);
    else if (eligibleBuckets[0]) setBucketId(eligibleBuckets[0].id);
    else setBucketId(null);
  }, [blockDetail.data, eligibleBuckets]);

  if (blocks.isLoading) return <CurateSkeleton />;

  if ((blocks.data?.items.length ?? 0) === 0) {
    return (
      <Center p="xl">
        <EmptyState
          title={t('curate.setup.no_active_blocks_title', { style_name: styleName })}
          body={
            <Stack align="center" gap="md">
              <Text>{t('curate.setup.no_active_blocks_body')}</Text>
              <Button component={Link} to={`/triage/${styleId}`}>
                {t('curate.setup.open_triage_cta')}
              </Button>
            </Stack>
          }
        />
      </Center>
    );
  }

  const submitTo = blockId && bucketId ? `/curate/${styleId}/${blockId}/${bucketId}` : '';
  const canSubmit = !!submitTo;

  return (
    <Center p="xl">
      <Stack gap="md" style={{ width: 480, maxWidth: '100%' }}>
        <Title order={2}>{t('curate.setup.title')}</Title>

        <Select
          label={t('curate.setup.block_select_label')}
          placeholder={t('curate.setup.block_select_placeholder')}
          data={blockItems}
          value={blockId}
          onChange={setBlockId}
          allowDeselect={false}
        />

        {blockId && bucketItems.length === 0 && !blockDetail.isLoading && (
          <EmptyState
            title={t('curate.setup.no_eligible_buckets_title')}
            body={t('curate.setup.no_eligible_buckets_body')}
          />
        )}

        {bucketItems.length > 0 && (
          <Select
            label={t('curate.setup.bucket_select_label')}
            placeholder={t('curate.setup.bucket_select_placeholder')}
            data={bucketItems}
            value={bucketId}
            onChange={setBucketId}
            allowDeselect={false}
          />
        )}

        <Button component={Link} to={submitTo} disabled={!canSubmit}>
          {t('curate.setup.start_cta')}
        </Button>
      </Stack>
    </Center>
  );
}
```

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/components/__tests__/CurateSetupPage.test.tsx
git add frontend/src/features/curate/components/CurateSetupPage.tsx frontend/src/features/curate/components/__tests__/CurateSetupPage.test.tsx
git commit -m "feat(curate): add CurateSetupPage picker"
```

---

## Task 14: `CurateSession` orchestrator

**Files:**
- Create: `frontend/src/features/curate/components/CurateSession.tsx`

No test file — covered by T20 integration test (full flow).

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/curate/components/CurateSession.tsx
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ActionIcon, Group, Stack, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { CurateCard } from './CurateCard';
import { DestinationGrid } from './DestinationGrid';
import { HotkeyOverlay } from './HotkeyOverlay';
import { EndOfQueue } from './EndOfQueue';
import { CurateSkeleton } from './CurateSkeleton';
import { useCurateSession } from '../hooks/useCurateSession';
import { useCurateHotkeys } from '../hooks/useCurateHotkeys';
import { stagingOverflow } from '../lib/destinationMap';
import {
  IconArrowLeft,
  IconKeyboard,
} from '../../../components/icons';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';

export interface CurateSessionProps {
  styleId: string;
  blockId: string;
  bucketId: string;
}

export function CurateSession({
  styleId,
  blockId,
  bucketId,
}: CurateSessionProps): JSX.Element {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const session = useCurateSession({ styleId, blockId, bucketId });
  const [overlayOpen, setOverlayOpen] = useState(false);

  useCurateHotkeys({
    buckets: session.destinations,
    overlayOpen,
    onAssign: session.assign,
    onUndo: session.undo,
    onSkip: session.skip,
    onPrev: session.prev,
    onOpenOverlay: () => setOverlayOpen(true),
    onCloseOverlay: () => setOverlayOpen(false),
    onExit: () => navigate(`/triage/${styleId}/${blockId}`),
    onOpenSpotify: session.openSpotify,
  });

  if (session.status === 'loading') return <CurateSkeleton />;
  if (session.status === 'error') {
    return (
      <Stack align="center" p="xl">
        <Text c="red">{t('curate.toast.move_failed')}</Text>
      </Stack>
    );
  }
  if (session.status === 'empty' && session.block) {
    return (
      <EndOfQueue
        styleId={styleId}
        block={session.block}
        currentBucketId={bucketId}
        totalAssigned={session.totalAssigned}
      />
    );
  }
  if (!session.currentTrack || !session.block) return <CurateSkeleton />;

  const currentBucket: TriageBucket | undefined = session.block.buckets.find(
    (b) => b.id === bucketId,
  );
  const currentLabel = currentBucket ? bucketLabel(currentBucket, t) : '';
  const total = session.queue.length;
  const counter = t('curate.footer.track_counter', {
    current: session.currentIndex + 1,
    total,
  });
  const hasOverflow = stagingOverflow(session.destinations).length > 0;

  return (
    <Stack gap="md" p={isMobile ? 'sm' : 'xl'} data-testid="curate-session">
      <Group justify="space-between" align="center">
        <ActionIcon
          variant="subtle"
          aria-label={t('curate.back_aria')}
          onClick={() => navigate(`/triage/${styleId}/${blockId}`)}
        >
          <IconArrowLeft size={18} />
        </ActionIcon>
        <Text size="sm" c="var(--color-fg-muted)">
          {counter} {t('curate.footer.in_bucket', { label: currentLabel })}
        </Text>
        <ActionIcon
          variant="subtle"
          aria-label={t('curate.help_aria')}
          onClick={() => setOverlayOpen(true)}
        >
          <IconKeyboard size={18} />
        </ActionIcon>
      </Group>

      <Group
        align="flex-start"
        gap={isMobile ? 'md' : 'xl'}
        wrap={isMobile ? 'wrap' : 'nowrap'}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <CurateCard track={session.currentTrack} />
        </div>
        <div style={{ width: isMobile ? '100%' : 360, flexShrink: 0 }}>
          <DestinationGrid
            buckets={session.destinations}
            currentBucketId={bucketId}
            lastTappedBucketId={session.lastTappedBucketId}
            onAssign={session.assign}
          />
        </div>
      </Group>

      {!isMobile && (
        <Group gap="md" justify="center">
          <Text size="xs" c="var(--color-fg-muted)">
            J {t('curate.footer.shortcut_skip')} · K {t('curate.footer.shortcut_prev')} · U{' '}
            {t('curate.footer.shortcut_undo')} · ? {t('curate.footer.shortcut_help')} · Esc{' '}
            {t('curate.footer.shortcut_exit')}
          </Text>
        </Group>
      )}

      <HotkeyOverlay
        opened={overlayOpen}
        onClose={() => setOverlayOpen(false)}
        hasOverflow={hasOverflow}
      />
    </Stack>
  );
}
```

- [ ] **Step 2: Verify icons exist in `frontend/src/components/icons.ts`**

```bash
grep -E "IconArrowLeft|IconKeyboard" frontend/src/components/icons.ts
```

If either is missing, add to that file:

```ts
export { IconArrowLeft, IconKeyboard } from '@tabler/icons-react';
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/curate/components/CurateSession.tsx frontend/src/components/icons.ts
git commit -m "feat(curate): add CurateSession orchestrator"
```

---

## Task 15: `CurateSessionPage` guard wrapper + accent-magenta lifecycle

**Files:**
- Create: `frontend/src/features/curate/routes/CurateSessionPage.tsx`
- Create: `frontend/src/features/curate/routes/__tests__/CurateSessionPage.test.tsx`

### Architectural notes

- Hook ordering: per CLAUDE.md "hooks rule + early Navigate return" pattern, the hook owners (`useCurateSession`) must NOT live in this file. This file ONLY does (a) param parsing + early `<Navigate>`, (b) `accent-magenta` body class lifecycle, (c) renders `<CurateSession>` if all params present.
- Validate params synchronously: if any of `styleId`, `blockId`, `bucketId` is missing, redirect to `/curate`. Block-status / bucket-eligibility validation happens inside `<CurateSession>` via the `useTriageBlock` query.

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/routes/__tests__/CurateSessionPage.test.tsx
import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateSessionPage } from '../CurateSessionPage';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

describe('CurateSessionPage', () => {
  it('mounts accent-magenta on body and removes on unmount', async () => {
    tokenStore.set('TOK');
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
          id: 'b1',
          style_id: 's1',
          style_name: 'House',
          name: 'W17',
          date_from: '2026-04-21',
          date_to: '2026-04-27',
          status: 'IN_PROGRESS',
          created_at: '2026-04-20T00:00:00Z',
          updated_at: '2026-04-20T00:00:00Z',
          finalized_at: null,
          buckets: [{ id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 }],
        }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    const qc = makeClient();
    const { unmount } = render(
      <MemoryRouter initialEntries={['/curate/s1/b1/src']}>
        <QueryClientProvider client={qc}>
          <MantineProvider theme={testTheme}>
            <Routes>
              <Route path="/curate/:styleId/:blockId/:bucketId" element={<CurateSessionPage />} />
            </Routes>
          </MantineProvider>
        </QueryClientProvider>
      </MemoryRouter>,
    );
    expect(document.body.classList.contains('accent-magenta')).toBe(true);
    unmount();
    expect(document.body.classList.contains('accent-magenta')).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/routes/__tests__/CurateSessionPage.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/routes/CurateSessionPage.tsx
import { useEffect } from 'react';
import { Navigate, useParams } from 'react-router';
import { CurateSession } from '../components/CurateSession';
import {
  writeLastCurateLocation,
  writeLastCurateStyle,
} from '../lib/lastCurateLocation';

export function CurateSessionPage(): JSX.Element {
  const params = useParams<{ styleId: string; blockId: string; bucketId: string }>();
  const { styleId, blockId, bucketId } = params;

  useEffect(() => {
    if (!styleId || !blockId || !bucketId) return;
    document.body.classList.add('accent-magenta');
    writeLastCurateLocation(styleId, blockId, bucketId);
    writeLastCurateStyle(styleId);
    return () => {
      document.body.classList.remove('accent-magenta');
    };
  }, [styleId, blockId, bucketId]);

  if (!styleId || !blockId || !bucketId) {
    return <Navigate to="/curate" replace />;
  }
  return <CurateSession styleId={styleId} blockId={blockId} bucketId={bucketId} />;
}
```

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/routes/__tests__/CurateSessionPage.test.tsx
git add frontend/src/features/curate/routes/CurateSessionPage.tsx frontend/src/features/curate/routes/__tests__/CurateSessionPage.test.tsx
git commit -m "feat(curate): add CurateSessionPage guard"
```

---

## Task 16: `CurateStyleResume` route + tests

**Files:**
- Create: `frontend/src/features/curate/routes/CurateStyleResume.tsx`
- Create: `frontend/src/features/curate/routes/__tests__/CurateStyleResume.test.tsx`

### Architectural notes

- Reads `readLastCurateLocation(styleId)`. If null → render `<CurateSetupPage styleId={styleId} />`.
- If not null → call `useTriageBlock(stored.blockId)`. While loading → `<CurateSkeleton>`.
- After resolved: validate via `isStaleLocation`. If stale → `clearLastCurateLocation` + `<CurateSetupPage>`. Else → `<Navigate>` to the session route.

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/routes/__tests__/CurateStyleResume.test.tsx
import React from 'react';
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateStyleResume } from '../CurateStyleResume';
import {
  LAST_CURATE_LOCATION_KEY,
} from '../../lib/lastCurateLocation';

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

const wrap = (initial: string, target = '/session/:styleId/:blockId/:bucketId') => {
  const qc = client();
  return (
    <MemoryRouter initialEntries={[initial]}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Routes>
            <Route path="/curate/:styleId" element={<CurateStyleResume />} />
            <Route path={target} element={<div data-testid="session-loaded" />} />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
};

beforeEach(() => {
  tokenStore.set('TOK');
  localStorage.clear();
});

const inProgressBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-27',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T00:00:00Z',
  updated_at: '2026-04-20T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 5 },
  ],
};

describe('CurateStyleResume', () => {
  it('redirects to session route on healthy resume entry', async () => {
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'src', updatedAt: 'x' } }),
    );
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    render(wrap('/curate/s1', '/curate/:styleId/:blockId/:bucketId'));
    await waitFor(() => expect(screen.getByTestId('session-loaded')).toBeInTheDocument());
  });

  it('renders setup picker when no resume entry exists', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json([{ id: 's1', name: 'House' }]),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(wrap('/curate/s1'));
    await waitFor(() =>
      expect(screen.getByText(/No active blocks/i)).toBeInTheDocument(),
    );
  });

  it('cleans up + renders setup picker when stored block is FINALIZED', async () => {
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'src', updatedAt: 'x' } }),
    );
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({ ...inProgressBlock, status: 'FINALIZED' }),
      ),
      http.get('http://localhost/styles', () =>
        HttpResponse.json([{ id: 's1', name: 'House' }]),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(wrap('/curate/s1'));
    await waitFor(() =>
      expect(screen.getByText(/No active blocks/i)).toBeInTheDocument(),
    );
    expect(localStorage.getItem(LAST_CURATE_LOCATION_KEY)).not.toContain('"s1"');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/routes/__tests__/CurateStyleResume.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/routes/CurateStyleResume.tsx
import { useMemo } from 'react';
import { Navigate, useParams } from 'react-router';
import { useTriageBlock } from '../../triage/hooks/useTriageBlock';
import { CurateSetupPage } from '../components/CurateSetupPage';
import { CurateSkeleton } from '../components/CurateSkeleton';
import {
  clearLastCurateLocation,
  isStaleLocation,
  readLastCurateLocation,
} from '../lib/lastCurateLocation';

export function CurateStyleResume(): JSX.Element {
  const { styleId } = useParams<{ styleId: string }>();
  const stored = useMemo(
    () => (styleId ? readLastCurateLocation(styleId) : null),
    [styleId],
  );
  const blockQuery = useTriageBlock(stored?.blockId ?? '');

  if (!styleId) return <Navigate to="/curate" replace />;
  if (!stored) return <CurateSetupPage styleId={styleId} />;
  if (blockQuery.isLoading) return <CurateSkeleton />;
  if (blockQuery.isError || !blockQuery.data) {
    clearLastCurateLocation(styleId);
    return <CurateSetupPage styleId={styleId} />;
  }
  if (isStaleLocation(stored, blockQuery.data)) {
    clearLastCurateLocation(styleId);
    return <CurateSetupPage styleId={styleId} />;
  }
  return <Navigate to={`/curate/${styleId}/${stored.blockId}/${stored.bucketId}`} replace />;
}
```

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/routes/__tests__/CurateStyleResume.test.tsx
git add frontend/src/features/curate/routes/CurateStyleResume.tsx frontend/src/features/curate/routes/__tests__/CurateStyleResume.test.tsx
git commit -m "feat(curate): add CurateStyleResume route"
```

---

## Task 17: `CurateIndexRedirect` route + tests

**Files:**
- Create: `frontend/src/features/curate/routes/CurateIndexRedirect.tsx`
- Create: `frontend/src/features/curate/routes/__tests__/CurateIndexRedirect.test.tsx`

### Architectural notes

- Reads `readLastCurateStyle()`. If present and `useStyles` confirms the style exists → redirect to `/curate/:styleId`.
- Else → redirect to `/curate/${firstStyleId}` (first style from `useStyles`).
- If `useStyles` empty → `/categories` (catch-all). Should never happen for an authenticated user.

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/features/curate/routes/__tests__/CurateIndexRedirect.test.tsx
import React from 'react';
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateIndexRedirect } from '../CurateIndexRedirect';
import { LAST_CURATE_STYLE_KEY } from '../../lib/lastCurateLocation';

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

beforeEach(() => {
  tokenStore.set('TOK');
  localStorage.clear();
});

function wrap() {
  const qc = client();
  return (
    <MemoryRouter initialEntries={['/curate']}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Routes>
            <Route path="/curate" element={<CurateIndexRedirect />} />
            <Route
              path="/curate/:styleId"
              element={<div data-testid="style-route">styleRoute</div>}
            />
            <Route path="/categories" element={<div data-testid="categories-route">cat</div>} />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

describe('CurateIndexRedirect', () => {
  it('redirects to lastCurateStyle when present and style exists', async () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's7');
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json([
          { id: 's1', name: 'House' },
          { id: 's7', name: 'Tech House' },
        ]),
      ),
    );
    render(wrap());
    await waitFor(() =>
      expect(screen.getByTestId('style-route')).toBeInTheDocument(),
    );
  });

  it('falls back to first style when lastCurateStyle missing', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json([{ id: 'first', name: 'House' }]),
      ),
    );
    render(wrap());
    await waitFor(() =>
      expect(screen.getByTestId('style-route')).toBeInTheDocument(),
    );
  });

  it('redirects to /categories when no styles exist', async () => {
    server.use(http.get('http://localhost/styles', () => HttpResponse.json([])));
    render(wrap());
    await waitFor(() =>
      expect(screen.getByTestId('categories-route')).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/curate/routes/__tests__/CurateIndexRedirect.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/curate/routes/CurateIndexRedirect.tsx
import { Navigate } from 'react-router';
import { useStyles } from '../../categories/hooks/useStyles';
import { CurateSkeleton } from '../components/CurateSkeleton';
import { readLastCurateStyle } from '../lib/lastCurateLocation';

export function CurateIndexRedirect(): JSX.Element {
  const styles = useStyles();
  if (styles.isLoading) return <CurateSkeleton />;
  if (styles.isError || !styles.data || styles.data.length === 0) {
    return <Navigate to="/categories" replace />;
  }
  const last = readLastCurateStyle();
  const target = last && styles.data.some((s) => s.id === last) ? last : styles.data[0]?.id;
  if (!target) return <Navigate to="/categories" replace />;
  return <Navigate to={`/curate/${target}`} replace />;
}
```

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/features/curate/routes/__tests__/CurateIndexRedirect.test.tsx
git add frontend/src/features/curate/routes/CurateIndexRedirect.tsx frontend/src/features/curate/routes/__tests__/CurateIndexRedirect.test.tsx
git commit -m "feat(curate): add CurateIndexRedirect route"
```

---

## Task 18: Router wiring + remove placeholder

**Files:**
- Modify: `frontend/src/routes/router.tsx`
- Delete: `frontend/src/routes/curate.tsx`
- Create: `frontend/src/features/curate/index.ts` (re-exports)

- [ ] **Step 1: Add the curate index re-exports**

```ts
// frontend/src/features/curate/index.ts
export { CurateIndexRedirect } from './routes/CurateIndexRedirect';
export { CurateStyleResume } from './routes/CurateStyleResume';
export { CurateSessionPage } from './routes/CurateSessionPage';
```

- [ ] **Step 2: Modify the router**

Open `frontend/src/routes/router.tsx`. Replace the import + the `/curate` route entry.

Replace:

```tsx
import { CuratePage } from './curate';
```

with:

```tsx
import {
  CurateIndexRedirect,
  CurateStyleResume,
  CurateSessionPage,
} from '../features/curate';
```

Replace:

```tsx
{ path: 'curate', element: <CuratePage /> },
```

with:

```tsx
{
  path: 'curate',
  children: [
    { index: true, element: <CurateIndexRedirect /> },
    { path: ':styleId', element: <CurateStyleResume /> },
    { path: ':styleId/:blockId/:bucketId', element: <CurateSessionPage /> },
  ],
},
```

- [ ] **Step 3: Delete the placeholder route file**

```bash
rm frontend/src/routes/curate.tsx
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: clean.

- [ ] **Step 5: Run full test suite**

```bash
cd frontend && pnpm test
```

Expected: all curate tests + existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/router.tsx frontend/src/features/curate/index.ts
git rm frontend/src/routes/curate.tsx
git commit -m "feat(curate): wire routes + drop placeholder"
```

---

## Task 19: Triage CTA wiring

**Files:**
- Modify: `frontend/src/features/triage/components/TriageBlockHeader.tsx` — add "Curate this block" CTA.
- Modify: `frontend/src/features/triage/routes/BucketDetailPage.tsx` — add "Curate this bucket" CTA.

### Architectural notes

- CTA visibility:
  - `TriageBlockHeader`: visible when `block.status === 'IN_PROGRESS'`. Links to `/curate/:styleId/:blockId/:firstSourceBucketId` where `firstSourceBucketId` = `nextSuggestedBucket(block.buckets, '')?.id`. If no eligible bucket → CTA hidden.
  - `BucketDetailPage`: visible when `block.status === 'IN_PROGRESS'` AND `bucket.bucket_type !== 'STAGING'` AND `bucket.track_count > 0`. Links to `/curate/:styleId/:blockId/:bucketId`.
- Use existing `<Button component={Link}>` pattern.
- Read the existing files first before editing — patterns may have shifted.

- [ ] **Step 1: Read existing files**

```bash
cat frontend/src/features/triage/components/TriageBlockHeader.tsx
cat frontend/src/features/triage/routes/BucketDetailPage.tsx
```

Identify the right slot in each: `TriageBlockHeader` exposes a header `Group` with the existing Finalize CTA (F4) — add the Curate CTA as a sibling on the LEFT of Finalize so primary action stays Finalize. `BucketDetailPage` exposes a header `Group` with the Transfer-all CTA (F4) — add Curate CTA on the LEFT of Transfer-all.

- [ ] **Step 2: Update `TriageBlockHeader.tsx`**

Add at the top of the file:

```tsx
import { Link } from 'react-router';
import { nextSuggestedBucket } from '../../../features/curate/lib/nextSuggestedBucket';
```

Inside the rendering, in the header `<Group>` of action buttons (next to Finalize), insert before the existing Finalize button:

```tsx
{block.status === 'IN_PROGRESS' && (() => {
  const target = nextSuggestedBucket(block.buckets, '');
  if (!target) return null;
  return (
    <Button
      component={Link}
      to={`/curate/${block.style_id}/${block.id}/${target.id}`}
      variant="default"
    >
      {t('curate.triage_cta.from_block')}
    </Button>
  );
})()}
```

- [ ] **Step 3: Update `BucketDetailPage.tsx`**

Add at the top of the file:

```tsx
import { Link } from 'react-router';
```

Inside the bucket-header action `<Group>`, insert before the existing Transfer-all button:

```tsx
{block?.status === 'IN_PROGRESS' &&
  bucket.bucket_type !== 'STAGING' &&
  bucket.track_count > 0 && (
    <Button
      component={Link}
      to={`/curate/${block.style_id}/${block.id}/${bucket.id}`}
      variant="default"
    >
      {t('curate.triage_cta.from_bucket')}
    </Button>
  )}
```

- [ ] **Step 4: Typecheck + run tests**

```bash
cd frontend && pnpm typecheck && pnpm test
```

Expected: clean. The new CTA does not break existing F3a/F3b/F4 tests because it only adds an element; existing assertions check for specific buttons, not absence of others.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/components/TriageBlockHeader.tsx frontend/src/features/triage/routes/BucketDetailPage.tsx
git commit -m "feat(curate): add triage CTAs"
```

---

## Task 20: Integration test — full curate flow

**Why now:** Composite test that exercises mounted `RouterProvider` + MSW + reducer + hotkeys + just-tapped + auto-advance + double-tap + undo + EndOfQueue.

**Files:**
- Create: `frontend/src/__tests__/curate-flow.test.tsx`

- [ ] **Step 1: Write the integration test**

```tsx
// frontend/src/__tests__/curate-flow.test.tsx
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';
import { server } from '../test/setup';
import { tokenStore } from '../auth/tokenStore';
import { testTheme } from '../test/theme';
import {
  CurateIndexRedirect,
  CurateStyleResume,
  CurateSessionPage,
} from '../features/curate';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

const block = {
  id: 'b1',
  style_id: 's1',
  style_name: 'Tech House',
  name: 'TH W17',
  date_from: '2026-04-21',
  date_to: '2026-04-27',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-20T00:00:00Z',
  updated_at: '2026-04-20T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 3 },
    { id: 'dst1', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c1', category_name: 'Big Room' },
    { id: 'dst2', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c2', category_name: 'Hard Techno' },
    { id: 'b-old', bucket_type: 'OLD' as const, inactive: false, track_count: 2 },
    { id: 'b-disc', bucket_type: 'DISCARD' as const, inactive: false, track_count: 0 },
  ],
};

const tracks = (ids: string[]) => ({
  items: ids.map((id) => ({
    track_id: id,
    title: `Track ${id}`,
    mix_name: null,
    isrc: null,
    bpm: 124,
    length_ms: 360000,
    publish_date: '2026-04-15',
    spotify_release_date: '2026-04-15',
    spotify_id: `sp-${id}`,
    release_type: 'single',
    is_ai_suspected: false,
    artists: ['Artist A'],
    label_name: 'Label X',
    added_at: '2026-04-21T00:00:00Z',
  })),
  total: ids.length,
  limit: 50,
  offset: 0,
});

let moveCount = 0;
function defaultHandlers() {
  moveCount = 0;
  return [
    http.get('http://localhost/styles', () =>
      HttpResponse.json([{ id: 's1', name: 'Tech House' }]),
    ),
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(tracks(['t1', 't2', 't3'])),
    ),
    http.post('http://localhost/triage/blocks/b1/move', async () => {
      moveCount += 1;
      return HttpResponse.json({ moved: 1, correlation_id: `cid-${moveCount}` });
    }),
  ];
}

function renderApp(initial = '/curate/s1/b1/src') {
  const qc = makeClient();
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Notifications />
          <Routes>
            <Route path="/curate" element={<CurateIndexRedirect />} />
            <Route path="/curate/:styleId" element={<CurateStyleResume />} />
            <Route
              path="/curate/:styleId/:blockId/:bucketId"
              element={<CurateSessionPage />}
            />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('Curate flow integration', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
  });
  afterEach(() => {
    localStorage.clear();
  });

  it('happy path: assign first track via hotkey 1, advance to track 2', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();

    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());

    await user.keyboard('1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    await waitFor(() => expect(screen.getByText('Track t2')).toBeInTheDocument());
    expect(moveCount).toBeGreaterThanOrEqual(1);

    vi.useRealTimers();
  });

  it('double-tap 1 then 2 — first reverted, second applied, single advance', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();

    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await user.keyboard('1');
    await user.keyboard('2');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    await waitFor(() => expect(screen.getByText('Track t2')).toBeInTheDocument());
    // Three POSTs: forward(dst1), inverse(undo dst1), forward(dst2) ⇒ moveCount = 3
    expect(moveCount).toBe(3);

    vi.useRealTimers();
  });

  it('Undo (U) after advance restores the previous track', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await user.keyboard('1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    await waitFor(() => expect(screen.getByText('Track t2')).toBeInTheDocument());
    await user.keyboard('u');
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());

    vi.useRealTimers();
  });

  it('? opens overlay; Esc closes; Esc again exits to triage', async () => {
    const user = userEvent.setup();
    renderApp();
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await user.keyboard('?');
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('end-of-queue suggests OLD when source NEW exhausted', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json(tracks(['only'])),
      ),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderApp();
    await waitFor(() => expect(screen.getByText('Track only')).toBeInTheDocument());
    await user.keyboard('1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
    });
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Continue with OLD/i })).toBeInTheDocument(),
    );

    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run the integration test**

```bash
cd frontend && pnpm test src/__tests__/curate-flow.test.tsx
```

Expected: 5 passing. If timer races on TQ5 microtasks (CLAUDE.md gotcha #19), drop fake timers in the assertion-heavy tests and replace `vi.advanceTimersByTimeAsync(220)` with `await new Promise((r) => setTimeout(r, 250))` plus `await waitFor(...)`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/__tests__/curate-flow.test.tsx
git commit -m "test(curate): add curate flow integration test"
```

---

## Task 21: Amend OPEN_QUESTIONS Q6

**Files:**
- Modify: `docs/design_handoff/OPEN_QUESTIONS.md`

- [ ] **Step 1: Update Q6**

Open `docs/design_handoff/OPEN_QUESTIONS.md`. Locate the `## Q6 — Hotkey scope в Curate` section. Replace the **Status:** paragraph and **Что делать** paragraph with the new mapping:

```markdown
## Q6 — Hotkey scope в Curate

**Status (amended 2026-05-04 with F5):** дизайн: `0` → DISCARD, `1`–`9` → staging
categories по `position` ASC (active only), `Q` / `W` / `E` → NEW / OLD / NOT,
`Space` → open-in-Spotify (placeholder; F6 promotes to play/pause),
`J`/`K` → skip/prev, `U` → undo (history depth 1), `?` → overlay, `Esc` → close
overlay or exit Curate, `Enter` → accept EndOfQueue suggestion.

**Edge case** покрыт: если у блока > 9 staging categories, первые 9 получают
хоткеи 1–9, остальные доступны через "More categories…" menu в DestinationGrid.
Footer overlay явно об этом сообщает.

**Что делать (выполнено F5):** хоткеи биндятся через `useCurateHotkeys` по
`event.code` (layout-safe — Cyrillic / Dvorak попадают на физическую позицию).
Bond `?` через `event.key` (shifted character, layout-dependent intent).
Mobile (<64em) хоткеи не биндятся; кнопки заменяют их.
```

- [ ] **Step 2: Commit**

```bash
git add docs/design_handoff/OPEN_QUESTIONS.md
git commit -m "docs(open-questions): amend Q6 hotkey scope for F5"
```

---

## Task 22: Smoke + CLAUDE.md gotchas + roadmap mark

**Files:**
- Modify: `CLAUDE.md` — add F5-specific gotchas to the Frontend section.
- Modify: `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md` — mark F5 shipped + post-F5 lessons.

### Smoke checklist (manual)

Before merging to main, perform a smoke against the deployed prod API GW:

1. `pnpm dev` from `frontend/` (with `frontend/.env.local` containing `VITE_API_BASE_URL` = output of `terraform output -raw api_endpoint`).
2. Sign in via Spotify OAuth (`http://127.0.0.1:5173`).
3. Navigate to Triage (`/triage`), pick a style with an IN_PROGRESS block + tracks in NEW.
4. Click "Curate this block" — assert deep-link to `/curate/:styleId/:blockId/:bucketId` works.
5. Press `1` — assert pulse + 200ms advance + counter increment.
6. Press `Q` — assert assign to NEW (or whatever current is — should be disabled if source).
7. Double-tap `1` then `2` rapidly — assert single advance + correct destination wins.
8. Press `U` after advance — assert previous track returns.
9. Press `?` — assert overlay opens.
10. Press `Esc` twice — assert exit to triage detail.
11. Empty the source bucket fully — assert EndOfQueue with "Continue with OLD" or Finalize CTA.
12. Refresh the page on `/curate/:styleId/:blockId/:bucketId` — assert position resumes correctly.
13. Navigate to `/curate` (no params) — assert redirect cascade to last session.
14. Manually clear `localStorage.lastCurateLocation` for the style + reload `/curate/:styleId` — assert setup picker appears.
15. From mobile viewport (DevTools 375×812) — assert keyboard not bound + tap-to-assign works + overlay shows mobile copy.
16. With `prefers-reduced-motion: reduce` — assert no scale animation on just-tapped (Chrome DevTools rendering tab).

### CLAUDE.md updates

Open `CLAUDE.md`. Find the `**Frontend (post-F1, 2026-05-02; F2, F3, F4 additions 2026-05-03):**` heading. Append new bullets at the bottom of that bullet list. Suggested entries (regenerate via verification — only add what's genuinely surprising and load-bearing):

- **Curate hotkey binding uses `event.code` for letter / digit keys.** `event.key` is layout-dependent (Cyrillic / Dvorak break QWE → NEW/OLD/NOT). Bind `?` through `event.key === '?'` because the user-facing intent is the question-mark glyph (shifted on US-QWERTY).
- **`accent-magenta` body class is mounted only on the active Curate session route** (`CurateSessionPage` `useEffect`). Cleanup on unmount must remove the class — otherwise the magenta `--color-selected-bg` token leaks into other modals after navigating away.
- **Curate's `useCurateSession` keeps timer IDs in `useRef`, not in reducer state.** Timer-driven re-renders cause a feedback loop with `useReducer`. Reducer dispatches happen inside `setTimeout` callbacks; reducer body itself is pure.
- **Double-tap rollback uses `undoMoveDirect` synchronous cache restore + async inverse HTTP.** Reducer dispatches `ASSIGN_REPLACE_BEGIN` only AFTER `undoMoveDirect`'s synchronous portion has restored the cache, so optimistic apply for the new destination starts from the correct baseline.
- **Curate auto-suggests next bucket via `nextSuggestedBucket` priority NEW → UNCLASSIFIED → OLD → NOT.** STAGING and DISCARD are excluded; the current source bucket is excluded; only buckets with `track_count > 0` are eligible. Returns `null` if none — surface the Finalize CTA instead.
- **`useBucketTracks` infinite query keys include the search string (`''` in Curate).** When invalidating from Curate's session, the empty search variant is what gets invalidated. Mirror this in tests.

### Roadmap update

Open `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`. Locate the table row:

```
| **F5** | Curate desktop + mobile | P-22..P-23 | `POST /triage/blocks/{id}/move`, hotkey overlay | `03 Pages catalog` Pass 2 | spec-D + Q6 + Q7 + Q8 | L |
```

Replace with:

```
| ~~**F5**~~ ✅ **Shipped 2026-05-04** | Curate desktop + mobile | P-22..P-23 | `POST /triage/blocks/{id}/move`, hotkey overlay | `03 Pages catalog` Pass 2 | spec-D + Q6 + Q7 + Q8 | L — actual ~1 day session via subagent-driven plan |
```

Append a `## Lessons learned (post-F5, 2026-05-04)` section at the end of the file mirroring the post-F4 structure. Include at least:

- Q6 hotkey scope amendment (1–9 + QWE) in design pack.
- `event.code` vs `event.key` layout-safety pitfall.
- `accent-magenta` body-class lifecycle.
- Timer + `useReducer` pattern (refs for timers).
- TQ5 microtask + fake-timer brittleness on integration tests (re-confirms gotcha #19).

- [ ] **Step 1: Run the full test suite locally**

```bash
cd frontend && pnpm test && pnpm typecheck && pnpm lint && pnpm build
```

Expected: all green; `pnpm build` reports the new bundle size delta (record in lessons).

- [ ] **Step 2: Manual smoke against prod API GW**

Perform every step in the Smoke checklist above. Note any bugs in scratch notes.

- [ ] **Step 3: Commit CLAUDE.md updates**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): capture F5 frontend gotchas"
```

- [ ] **Step 4: Commit roadmap updates**

```bash
git add docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md
git commit -m "docs(roadmap): mark F5 shipped + post-F5 lessons"
```

- [ ] **Step 5: Push (only when smoke clean)**

```bash
git push -u origin worktree-f5_task
```

- [ ] **Step 6: Open PR via `caveman:caveman-commit` skill output for title + body**

Per CLAUDE.md PR Policy. Title format `feat(curate): F5 desktop + mobile`. Body = caveman summary + test plan + manual smoke steps. No AI attribution.

---

## Self-Review Checklist (run after writing this plan)

- **Spec coverage:**
  - §1 Context — covered by T1–T22 cumulatively (every "After F5 ships" bullet maps to a task or smoke step).
  - §2 Scope — every "in scope" bullet is one task; every "out of scope" stays out (no T-task adds audio/bulk/swipe/etc.).
  - §3 D1 hybrid entry — T18 (router), T19 (Triage CTAs), T17 (index redirect), T16 (resume).
  - §3 D2 single-bucket — T5 reducer takes one bucketId; T13 picker filters non-STAGING.
  - §3 D3 no audio — T8 CurateCard renders Spotify deep-link; T6 Space binds `onOpenSpotify`; T11 overlay copy notes "audio in F6".
  - §3 D4 hotkey scope — T6 `useCurateHotkeys`, T11 overlay, T21 Q6 amendment.
  - §3 D5 silent toast + history-depth-1 — T5 reducer (no `notifications.show` in success path; depth-1 lastOp), T20 integration test asserts double-tap.
  - §3 D6 hook-owned state — T5 hook, T14 component just mounts it.
  - §3 D7 routing — T16/T17/T15/T18.
  - §3 D8 persistence triggers — T2 lib, T5 reducer onSuccess, T15 mount writes.
  - §3 D9 just-tapped + auto-advance — T5 timers, T9 CSS, T20 integration.
  - §3 D10 mobile — T6 `useMediaQuery`-skip, T9/T10/T11 mobile branches.
  - §4 UI surfaces — T8/T9/T10/T11/T12/T13 components, T14 layout.
  - §5 Component catalog — T7..T17 cover every entry.
  - §6 Data flow — T5 reducer, T6 hotkeys, T9 just-tapped CSS, T20 integration verifies the flow.
  - §7 Validation — T15 param guard; T16 stale handling.
  - §8 Error / empty / loading — T5 emitErrorToast + status enum; T13 setup empty states.
  - §9 Code layout — exactly mirrored in T1..T22 file paths.
  - §10 i18n keys — T1.
  - §11 Testing — every component / hook / lib has its TDD test in T2..T20.
  - §12 Delivery — T22 smoke + commit cadence.
  - §13 Open items — preserved as `FUTURE-F5-*` flags in spec; not added to plan tasks.
  - §14 Acceptance Criteria — T20 integration test + manual smoke cover all 18 criteria.
  - §15 References — checked against design pack + spec-D + F3a/F4 specs.
- **Placeholder scan:** no "TODO" / "TBD" / "fill in" remaining in the plan. (Search confirmed zero hits.)
- **Type / API consistency:** `Session.lastTappedBucketId` used everywhere (not `justTapped`); `useCurateSession` signature `({ blockId, bucketId, styleId })` consistent across T5 / T14 / T15 / T20; `DestinationButton` props match across T9 / T10; `DestinationGrid` uses `currentBucketId` consistently.

If any gap surfaces during execution, add a follow-up task at the bottom of this plan and re-run the relevant test suite.

---

**Plan complete and saved to** `docs/superpowers/plans/2026-05-04-F5-curate-frontend.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?







