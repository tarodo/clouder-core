# Artist Enrichment — SP2 Plan 2C: Player Panel + Preferences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface enriched artist info on all three players (a full card for the main artist + chips for every other artist), plus like/dislike preferences across Library and players, completing the artist-enrichment feature end to end.

**Architecture:** Mirror the proven label-player components with parallel `Artist*`-prefixed files under `features/library/`. The one genuinely new component is `ArtistsPanel` (main artist → full `ArtistTile`, every other artist → an expandable chip). Reuse the entity-agnostic `countryFlag`/`ARTIST_CHANNELS`/icons and the react-query patterns. Preferences mirror `useSetLabelPreference` exactly (`PUT /artists/{id}/preference`).

**Tech Stack:** Vite + React 19 + Mantine 9, TanStack Query v5, react-router, vitest (jsdom) + `@vitest/browser`+Playwright (`*.browser.test.tsx`), openapi-typescript-generated `api/schema.d.ts`.

---

## Context the implementer must know

**Worktree root:** `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/improve_artist_search`. All paths below are under `frontend/`. The branch already carries SP2 plans 2A (Library list/detail + `api/artists.ts` + read hooks) and 2B (admin). This plan is 2C — the last.

**Commands** (run from `frontend/`):
- `pnpm test <path>` — vitest jsdom (no stylesheets applied).
- `pnpm test:browser <path>` — `@vitest/browser` + Playwright; the ONLY way to verify CSS/layout (CLAUDE.md gotcha #11). Run locally; CI has no browser.
- `pnpm typecheck` — `tsc --noEmit`. Must stay at 0 errors.
- Commits go through the `caveman:caveman-commit` skill, then `git commit`. Conventional Commits. NO `Co-Authored-By`/AI trailer (a hook strips it and blocks the commit). Branch is already `worktree-improve_artist_search` — do NOT create a new branch.

**Data facts established during planning (do not re-investigate):**

1. **Preference endpoint exists.** `PUT /artists/{artist_id}/preference`, body `{ "status": "liked" | "disliked" | "none" }`, returns 204. `"none"` clears. (`schema.d.ts` line ~6189.)
2. **`my` filter exists** on `GET /artists`: query `my?: "all" | "liked" | "disliked" | "unrated"`. `useArtistsList` already forwards it; `ArtistsListPage` currently hardcodes `my="all"` + `hideMyFilter` (2A deferral). 2C re-enables it.
3. **`my_preference` field shape:**
   - `ArtistSummary` (list item): `my_preference?: "liked" | "disliked" | null` at the **top level** (sibling of `info`, not inside `info`). Also carries `id`, `name`, `track_count`, `status`, and `info?: { country?, active_since?, ai_content?, primary_styles?, tagline?, ... } | null`.
   - `ArtistDetail`: `my_preference?: "liked" | "disliked" | null` at the top level; the rest is an open `{ [key: string]: unknown }` record (read via `rec[...]` casts, as the existing `ArtistDetailHeader`/`ArtistOverviewTab` do).
4. **Artist roles are uniform today.** Beatport ingest writes every `clouder_track_artists.role` as `"main"` (`src/collector/canonicalize.py:415`). So "main artist" selection is **order-based**: `artists[0]` is the main artist, `artists.slice(1)` are the others. `role` is informational; surface it on a chip only when `role && role !== 'main'`.
5. **Per-track artist arrays already flow to the players:**
   - `BucketTrack.artists: { id: string; name: string; role: string }[]` (2A backend touch). Reached in `BucketPlayerPanel` via `effectiveRich`.
   - `CategoryTrack.artists: { id: string; name: string }[]` (`TrackArtist`, no role). Reached via `effectiveRich`. `CategoryPlayerPanel` already receives a `styleId` prop.
   - `PlaylistTrack.artists: { id: string; name: string }[]` (`PlaylistTrackArtist`, no role). Reached via `effectiveRich`. **No `styleId`** — a playlist track has no style context.
6. **`ArtistTile` deep-link needs `styleId` only for the optional library cross-link.** The artist *info* (name/country/active_since/bio/collaborators/channels/AI/preference) needs no styleId. So `ArtistTile` takes `styleId?: string`: present → artist name is an `Anchor` to `/library/{styleId}/artists/{artistId}`; absent (playlist) → artist name is plain `Text`. The full panel still renders on the playlist player (spec decision), just without the cross-link.
7. **AI badge.** `ai_content` values map to colors via `AI_COLOR = { none_detected:'green', unknown:'gray', suspected:'yellow', confirmed:'red' }`; label text is `AI ${value.toUpperCase()}`. This pair is currently duplicated in `LabelDetailHeader.tsx` and `ArtistDetailHeader.tsx`. Task 3 factors an artist-side shared helper and reuses it; leave `LabelDetailHeader` untouched (avoid label-side risk).
8. **Existing artist read hooks (built in 2A), reuse as-is:**
   - `useArtistInfo(id)` → `['artistInfo', id]` → `GET /artists/{id}` (404-aware retry). Used by the player tile.
   - `useArtistDetail(id)` → `['library','artistDetail', id]` → `GET /artists/{id}`. Used by the detail page.
   - `useArtistsList(params)` → `['library','artists', styleId, q, sort, my, page, limit]`.
9. **Preference buttons reuse icons** from `../../../components/icons` (module `frontend/src/components/icons.ts`): `IconThumbUp`, `IconThumbUpFilled`, `IconThumbDown`, `IconThumbDownFilled`.
10. **i18n** lives in `frontend/src/i18n/en.json`. Existing keys to reuse: `library.detail.active_since` (`"Active since {{year}}"`), `library.detail.notable_collaborators`, `library.detail.ai_reasoning_missing`, `library.channels.*`, `library.prefs.unset_aria`. New keys are added per task.

---

## File structure (created / modified by this plan)

- Create `frontend/src/features/library/hooks/useSetArtistPreference.ts` — optimistic preference mutation.
- Create `frontend/src/features/library/components/ArtistPreferenceButtons.tsx` — like/dislike buttons.
- Create `frontend/src/features/library/lib/aiContent.tsx` — shared `AI_COLOR` + `formatAiContent` + `<AiContentBadge>`.
- Create `frontend/src/features/library/components/ArtistTile.tsx` — full artist card for the player.
- Create `frontend/src/features/library/components/ArtistsPanel.tsx` — main tile + expandable chips.
- Modify `frontend/src/features/library/components/ArtistDetailHeader.tsx` — add preference buttons + use shared badge.
- Modify `frontend/src/features/library/components/ArtistsTable.tsx` — add a preference column.
- Modify `frontend/src/features/library/routes/ArtistsListPage.tsx` — wire the `my` filter from the URL.
- Modify `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — render `ArtistsPanel`.
- Modify `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` — render `ArtistsPanel`.
- Modify `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx` — render `ArtistsPanel`.
- Modify `frontend/src/i18n/en.json` — add artist-preference + panel keys.
- Test files alongside each (`__tests__/*.test.tsx`) + one `*.browser.test.tsx`.

---

## Task 1: `useSetArtistPreference` hook + `ArtistPreferenceButtons`

**Files:**
- Create: `frontend/src/features/library/hooks/useSetArtistPreference.ts`
- Create: `frontend/src/features/library/components/ArtistPreferenceButtons.tsx`
- Modify: `frontend/src/i18n/en.json`
- Test: `frontend/src/features/library/hooks/__tests__/useSetArtistPreference.test.tsx`

- [ ] **Step 1: Write the failing test for the hook**

Create `frontend/src/features/library/hooks/__tests__/useSetArtistPreference.test.tsx`:

```tsx
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { useSetArtistPreference } from '../useSetArtistPreference';
import { artistInfoKey } from '../useArtistInfo';
import { artistDetailKey } from '../useArtistDetail';
import * as client from '../../../../api/client';

function wrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useSetArtistPreference', () => {
  beforeEach(() => vi.restoreAllMocks());

  test('PUTs status and optimistically patches info, detail, and list caches', async () => {
    const apiSpy = vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    qc.setQueryData(artistInfoKey('a1'), { artist_name: 'A1', my_preference: null });
    qc.setQueryData(artistDetailKey('a1'), { artist_name: 'A1', my_preference: null });
    qc.setQueryData(
      ['library', 'artists', 'techno', '', 'name', 'all', 1, 25],
      { items: [{ id: 'a1', name: 'A1', my_preference: null }], total: 1, page: 1, limit: 25 },
    );

    const { result } = renderHook(() => useSetArtistPreference(), { wrapper: wrapper(qc) });
    result.current.mutate({ artistId: 'a1', status: 'liked' });

    await waitFor(() => {
      expect((qc.getQueryData(artistInfoKey('a1')) as { my_preference?: string }).my_preference).toBe('liked');
    });
    expect((qc.getQueryData(artistDetailKey('a1')) as { my_preference?: string }).my_preference).toBe('liked');
    const list = qc.getQueryData(['library', 'artists', 'techno', '', 'name', 'all', 1, 25]) as {
      items: Array<{ id: string; my_preference?: string | null }>;
    };
    expect(list.items[0].my_preference).toBe('liked');
    expect(apiSpy).toHaveBeenCalledWith('/artists/a1/preference', {
      method: 'PUT',
      body: JSON.stringify({ status: 'liked' }),
    });
  });

  test('rolls back caches when the request fails', async () => {
    vi.spyOn(client, 'api').mockRejectedValue(new Error('boom'));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(artistInfoKey('a1'), { artist_name: 'A1', my_preference: null });

    const { result } = renderHook(() => useSetArtistPreference(), { wrapper: wrapper(qc) });
    result.current.mutate({ artistId: 'a1', status: 'disliked' });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((qc.getQueryData(artistInfoKey('a1')) as { my_preference?: string | null }).my_preference).toBe(null);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm test src/features/library/hooks/__tests__/useSetArtistPreference.test.tsx`
Expected: FAIL — `Cannot find module '../useSetArtistPreference'`.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/features/library/hooks/useSetArtistPreference.ts` (mirror of `useSetLabelPreference.ts`, patching the three artist caches):

```ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { artistInfoKey } from './useArtistInfo';
import { artistDetailKey } from './useArtistDetail';

export type ArtistPreference = 'liked' | 'disliked' | null;
export type PreferenceMutationStatus = 'liked' | 'disliked' | 'none';

interface Variables {
  artistId: string;
  status: PreferenceMutationStatus;
}

interface Snapshot {
  key: readonly unknown[];
  data: unknown;
}

export function useSetArtistPreference() {
  const qc = useQueryClient();
  return useMutation<void, Error, Variables, { snapshots: Snapshot[] }>({
    mutationFn: ({ artistId, status }) =>
      api<void>(`/artists/${artistId}/preference`, {
        method: 'PUT',
        body: JSON.stringify({ status }),
      }),
    onMutate: ({ artistId, status }) => {
      const next: ArtistPreference = status === 'none' ? null : status;
      const snapshots: Snapshot[] = [];

      // Single-keyed caches: artistInfo (player tile) + artistDetail (detail page).
      for (const key of [artistInfoKey(artistId), artistDetailKey(artistId)]) {
        const data = qc.getQueryData(key);
        if (data !== undefined) {
          snapshots.push({ key, data });
          qc.setQueryData(key, {
            ...(data as Record<string, unknown>),
            my_preference: next,
          });
        }
      }

      // artistsList: many queries — patch the matching row in each.
      const lists = qc.getQueriesData<{ items?: Array<Record<string, unknown>> }>({
        queryKey: ['library', 'artists'],
      });
      for (const [key, data] of lists) {
        if (!data || !Array.isArray(data.items)) continue;
        if (!data.items.some((it) => (it as { id?: string }).id === artistId)) continue;
        snapshots.push({ key, data });
        qc.setQueryData(key, {
          ...data,
          items: data.items.map((it) =>
            (it as { id?: string }).id === artistId ? { ...it, my_preference: next } : it,
          ),
        });
      }

      return { snapshots };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      for (const snap of ctx.snapshots) qc.setQueryData(snap.key, snap.data);
    },
    onSettled: (_data, _err, { artistId }) => {
      void qc.invalidateQueries({ queryKey: artistInfoKey(artistId) });
      void qc.invalidateQueries({ queryKey: artistDetailKey(artistId) });
    },
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm test src/features/library/hooks/__tests__/useSetArtistPreference.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Add i18n keys for artist preference**

In `frontend/src/i18n/en.json`, extend the `library.prefs` block (currently `like_aria`/`dislike_aria`/`unset_aria`) to add artist-specific aria labels:

```json
    "prefs": {
      "like_aria": "Like label",
      "dislike_aria": "Dislike label",
      "unset_aria": "Remove preference",
      "like_artist_aria": "Like artist",
      "dislike_artist_aria": "Dislike artist"
    },
```

- [ ] **Step 6: Implement `ArtistPreferenceButtons`**

Create `frontend/src/features/library/components/ArtistPreferenceButtons.tsx` (mirror of `LabelPreferenceButtons.tsx`, artist endpoint + aria keys):

```tsx
import { ActionIcon, Group } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  IconThumbUp,
  IconThumbUpFilled,
  IconThumbDown,
  IconThumbDownFilled,
} from '../../../components/icons';
import {
  useSetArtistPreference,
  type ArtistPreference,
} from '../hooks/useSetArtistPreference';

interface Props {
  artistId: string;
  current: ArtistPreference;
  size?: 'sm' | 'md';
}

export function ArtistPreferenceButtons({ artistId, current, size = 'sm' }: Props) {
  const { t } = useTranslation();
  const mutation = useSetArtistPreference();

  const iconSize = size === 'md' ? 18 : 14;
  const liked = current === 'liked';
  const disliked = current === 'disliked';

  const onLike = () =>
    mutation.mutate({ artistId, status: liked ? 'none' : 'liked' });
  const onDislike = () =>
    mutation.mutate({ artistId, status: disliked ? 'none' : 'disliked' });

  return (
    <Group gap={4} wrap="nowrap">
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onLike}
        aria-label={liked ? t('library.prefs.unset_aria') : t('library.prefs.like_artist_aria')}
      >
        {liked ? (
          <IconThumbUpFilled size={iconSize} color="var(--mantine-color-dark-9)" />
        ) : (
          <IconThumbUp size={iconSize} />
        )}
      </ActionIcon>
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onDislike}
        aria-label={disliked ? t('library.prefs.unset_aria') : t('library.prefs.dislike_artist_aria')}
      >
        {disliked ? (
          <IconThumbDownFilled size={iconSize} color="var(--mantine-color-dark-9)" />
        ) : (
          <IconThumbDown size={iconSize} />
        )}
      </ActionIcon>
    </Group>
  );
}
```

- [ ] **Step 7: Typecheck**

Run: `pnpm typecheck`
Expected: 0 errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/library/hooks/useSetArtistPreference.ts \
        frontend/src/features/library/hooks/__tests__/useSetArtistPreference.test.tsx \
        frontend/src/features/library/components/ArtistPreferenceButtons.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(library): add artist preference hook and buttons"
```

---

## Task 2: Wire preferences into Library (detail header, table column, my-filter)

**Files:**
- Modify: `frontend/src/features/library/components/ArtistDetailHeader.tsx`
- Modify: `frontend/src/features/library/components/ArtistsTable.tsx`
- Modify: `frontend/src/features/library/routes/ArtistsListPage.tsx`
- Modify: `frontend/src/i18n/en.json`
- Test: `frontend/src/features/library/components/__tests__/ArtistsTable.preference.test.tsx`

- [ ] **Step 1: Write the failing test for the table preference column**

Create `frontend/src/features/library/components/__tests__/ArtistsTable.preference.test.tsx`:

```tsx
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { ArtistsTable } from '../ArtistsTable';
import type { ArtistSummary } from '../../../../api/artists';

function renderTable(items: ArtistSummary[]) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistsTable
            items={items}
            styleId="techno"
            isLoading={false}
            page={1}
            pageCount={1}
            onPageChange={() => {}}
          />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistsTable — preference column', () => {
  test('renders like/dislike buttons per row reflecting my_preference', () => {
    renderTable([
      {
        id: 'a1', name: 'Artist One', style: 'techno', status: 'completed',
        track_count: 3, info: { country: 'DE' }, my_preference: 'liked',
      } as ArtistSummary,
    ]);
    // Liked state → the "remove preference" aria is shown on the (filled) like button.
    expect(screen.getByRole('button', { name: 'Remove preference' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dislike artist' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm test src/features/library/components/__tests__/ArtistsTable.preference.test.tsx`
Expected: FAIL — no button with name "Remove preference" (no preference column yet).

- [ ] **Step 3: Add the preference column to `ArtistsTable`**

In `frontend/src/features/library/components/ArtistsTable.tsx`:

Add the import near the other imports:

```tsx
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';
```

Add a header cell after the AI column header and before the description header:

```tsx
            <Table.Th>{t('library.list.col_ai_detected')}</Table.Th>
            <Table.Th>{t('library.artists_list.col_preference')}</Table.Th>
            <Table.Th>{t('library.list.col_description')}</Table.Th>
```

Add the matching body cell after the AI `<Table.Td>` and before the description `<Table.Td>`:

```tsx
                <Table.Td>
                  <ArtistPreferenceButtons
                    artistId={it.id}
                    current={it.my_preference ?? null}
                    size="sm"
                  />
                </Table.Td>
```

- [ ] **Step 4: Run the table test to verify it passes**

Run: `pnpm test src/features/library/components/__tests__/ArtistsTable.preference.test.tsx`
Expected: PASS.

- [ ] **Step 5: Add the `col_preference` i18n key**

In `frontend/src/i18n/en.json`, extend `library.artists_list`:

```json
    "artists_list": {
      "title": "Artists",
      "col_active_since": "Active since",
      "col_preference": "Preference"
    },
```

- [ ] **Step 6: Add preference buttons to `ArtistDetailHeader`**

In `frontend/src/features/library/components/ArtistDetailHeader.tsx`:

Add the import:

```tsx
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';
```

Read the preference from the record (add beside the existing `aiContent`/`aiReasoning` reads):

```tsx
  const myPreference =
    rec.my_preference === 'liked' || rec.my_preference === 'disliked'
      ? rec.my_preference
      : null;
```

Render the buttons in the title row, after the AI badge. The component receives `artistId` as a prop (already in `Props`, currently unused — destructure it):

Change the signature from `export function ArtistDetailHeader({ info, styleId }: Props) {` to:

```tsx
export function ArtistDetailHeader({ info, styleId, artistId }: Props) {
```

And the title `Group`:

```tsx
      <Group gap="sm" mt="xs" align="center" wrap="wrap">
        <Title order={2}>{artistName}</Title>
        {aiBadge}
        <ArtistPreferenceButtons artistId={artistId} current={myPreference} size="md" />
      </Group>
```

- [ ] **Step 7: Wire the `my` filter in `ArtistsListPage`**

In `frontend/src/features/library/routes/ArtistsListPage.tsx`, mirror `LibraryListPage`'s `my` handling.

Add to imports (the hook already exports the type):

```tsx
import { useArtistsList, type ArtistsListMy } from '../hooks/useArtistsList';
```

Add the `my` reader near the top of the module (after imports, before the component):

```tsx
const MY_VALUES: ReadonlySet<ArtistsListMy> = new Set(['all', 'liked', 'disliked', 'unrated']);

function readMy(raw: string | null): ArtistsListMy {
  if (raw && MY_VALUES.has(raw as ArtistsListMy)) return raw as ArtistsListMy;
  return 'all';
}
```

Inside the component, read it from the URL (beside the other `searchParams.get` reads):

```tsx
  const my = readMy(searchParams.get('my'));
```

Pass it to the query (replace `my: 'all'`):

```tsx
  const query = useArtistsList({
    styleId: styleId ?? '',
    q,
    sort,
    page,
    limit: PAGE_SIZE,
    my,
  });
```

Update `LibraryFilters`: pass the real `my` and an `onMyChange`, and remove `hideMyFilter`:

```tsx
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
```

- [ ] **Step 8: Run the full library suite + typecheck**

Run: `pnpm test src/features/library`
Expected: PASS (existing 2A tests + the new preference test).
Run: `pnpm typecheck`
Expected: 0 errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/library/components/ArtistDetailHeader.tsx \
        frontend/src/features/library/components/ArtistsTable.tsx \
        frontend/src/features/library/components/__tests__/ArtistsTable.preference.test.tsx \
        frontend/src/features/library/routes/ArtistsListPage.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(library): wire artist preferences into table, detail, and my-filter"
```

---

## Task 3: shared AI badge helper + `ArtistTile`

**Files:**
- Create: `frontend/src/features/library/lib/aiContent.tsx`
- Create: `frontend/src/features/library/components/ArtistTile.tsx`
- Modify: `frontend/src/features/library/components/ArtistDetailHeader.tsx` (reuse the shared badge)
- Test: `frontend/src/features/library/components/__tests__/ArtistTile.test.tsx`

- [ ] **Step 1: Create the shared AI-content helper**

Create `frontend/src/features/library/lib/aiContent.tsx`:

```tsx
import { Badge, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export const AI_COLOR: Record<string, string> = {
  none_detected: 'green',
  unknown: 'gray',
  suspected: 'yellow',
  confirmed: 'red',
};

export function formatAiContent(value: string): string {
  return `AI ${value.toUpperCase()}`;
}

interface AiContentBadgeProps {
  /** ai_content enum value; empty string renders nothing. */
  content: string;
  reasoning?: string;
  /** 'colored' (detail header) or 'outline' (compact player tile). */
  variant?: 'colored' | 'outline';
}

/** Tooltip-wrapped AI badge. Returns null when `content` is empty. */
export function AiContentBadge({ content, reasoning = '', variant = 'colored' }: AiContentBadgeProps) {
  const { t } = useTranslation();
  if (!content) return null;

  const badge =
    variant === 'outline' ? (
      <Badge
        variant="outline"
        style={{ cursor: 'help', backgroundColor: 'white', color: 'black', borderColor: 'black' }}
      >
        {formatAiContent(content)}
      </Badge>
    ) : (
      <Badge color={AI_COLOR[content] ?? 'gray'} variant="light" style={{ cursor: 'help' }}>
        {formatAiContent(content)}
      </Badge>
    );

  return (
    <Tooltip
      label={reasoning || t('library.detail.ai_reasoning_missing')}
      multiline
      w={300}
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
      {badge}
    </Tooltip>
  );
}
```

- [ ] **Step 2: Reuse the shared badge in `ArtistDetailHeader`**

In `frontend/src/features/library/components/ArtistDetailHeader.tsx`, remove the local `AI_COLOR` const, the local `formatAiContent`, and the inline `aiBadge` `Tooltip`/`Badge` JSX, replacing them with the shared component. Add the import:

```tsx
import { AiContentBadge } from '../lib/aiContent';
```

Keep reading `aiContent`/`aiReasoning` from `rec`, then render in the title group (replacing `{aiBadge}`):

```tsx
        <AiContentBadge content={aiContent} reasoning={aiReasoning} variant="colored" />
```

Delete the now-unused `AI_COLOR`/`formatAiContent`/`aiBadge` definitions. (Leave `LabelDetailHeader.tsx` untouched — it keeps its own copy to avoid label-side churn.)

- [ ] **Step 3: Write the failing test for `ArtistTile`**

Create `frontend/src/features/library/components/__tests__/ArtistTile.test.tsx`:

```tsx
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { ArtistTile } from '../ArtistTile';
import { artistInfoKey } from '../../hooks/useArtistInfo';
import * as client from '../../../../api/client';

function renderTile(props: { artistId: string | null; artistName?: string; styleId?: string }, seed?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (seed && props.artistId) qc.setQueryData(artistInfoKey(props.artistId), seed);
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistTile {...props} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistTile', () => {
  beforeEach(() => vi.restoreAllMocks());

  test('returns nothing when artistId is null', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    const { container } = renderTile({ artistId: null });
    expect(container).toBeEmptyDOMElement();
  });

  test('renders enriched info: name links to library detail when styleId is given', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderTile(
      { artistId: 'a1', artistName: 'A1', styleId: 'techno' },
      {
        artist_name: 'Aphex',
        country: 'GB',
        active_since: 1991,
        summary: 'Pioneer.',
        notable_collaborators: ['AFX'],
        ai_content: 'confirmed',
        ai_reasoning: 'Synthetic vocals.',
        my_preference: null,
      },
    );
    const link = screen.getByRole('link', { name: 'Aphex' });
    expect(link).toHaveAttribute('href', '/library/techno/artists/a1');
    expect(screen.getByText('Pioneer.')).toBeInTheDocument();
    expect(screen.getByText('AI CONFIRMED')).toBeInTheDocument();
  });

  test('renders artist name as plain text (no link) when styleId is absent', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderTile({ artistId: 'a1', artistName: 'A1' }, { artist_name: 'NoStyle', my_preference: null });
    expect(screen.queryByRole('link', { name: 'NoStyle' })).toBeNull();
    expect(screen.getByText('NoStyle')).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pnpm test src/features/library/components/__tests__/ArtistTile.test.tsx`
Expected: FAIL — `Cannot find module '../ArtistTile'`.

- [ ] **Step 5: Implement `ArtistTile`**

Create `frontend/src/features/library/components/ArtistTile.tsx` (mirror of `LabelTile.tsx`; artist fields; optional cross-link; shared AI badge; reuse `ARTIST_CHANNELS`):

```tsx
import { Anchor, ActionIcon, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useArtistInfo } from '../hooks/useArtistInfo';
import { countryFlag } from '../lib/countryFlag';
import { ARTIST_CHANNELS } from '../lib/artistChannelMeta';
import { AiContentBadge } from '../lib/aiContent';
import { ArtistPreferenceButtons } from './ArtistPreferenceButtons';

interface Props {
  artistId: string | null | undefined;
  artistName?: string | null | undefined;
  /** Present on bucket/category players → name links to library detail. Absent on playlists. */
  styleId?: string;
}

interface ArtistInfoView {
  artist_name?: string;
  country?: string | null;
  active_since?: number | null;
  tagline?: string | null;
  summary?: string | null;
  bio?: string | null;
  notable_collaborators?: string[] | null;
  ai_content?: string | null;
  ai_reasoning?: string | null;
  my_preference?: 'liked' | 'disliked' | null;
}

function pickPreference(value: unknown): 'liked' | 'disliked' | null {
  return value === 'liked' || value === 'disliked' ? value : null;
}

export function ArtistTile({ artistId, artistName, styleId }: Props) {
  const { t } = useTranslation();
  const query = useArtistInfo(artistId);

  if (!artistId) return null;

  const info = query.data as ArtistInfoView | undefined;
  const displayName = info?.artist_name ?? artistName ?? '';
  const preference = pickPreference(info?.my_preference ?? null);

  const hasEnrichment = !!info && (
    !!info.summary ||
    !!info.bio ||
    !!info.tagline ||
    !!info.country ||
    info.active_since != null ||
    (Array.isArray(info.notable_collaborators) && info.notable_collaborators.length > 0)
  );
  const showFullCard = !query.isLoading && !query.isError && hasEnrichment;

  const aiContent = info?.ai_content ?? '';
  const aiReasoning = info?.ai_reasoning ?? '';
  const collaborators = Array.isArray(info?.notable_collaborators)
    ? info!.notable_collaborators!.filter((a): a is string => typeof a === 'string')
    : [];
  const channels = showFullCard
    ? ARTIST_CHANNELS.flatMap((ch) => {
        const url = (info as Record<string, unknown>)[ch.field];
        if (typeof url !== 'string' || !url) return [];
        return [{ ...ch, url }];
      })
    : [];

  const nameNode = styleId ? (
    <Anchor component={Link} to={`/library/${styleId}/artists/${artistId}`} fw={600} size="lg">
      {displayName || artistId}
    </Anchor>
  ) : (
    <Text fw={600} size="lg">
      {displayName || artistId}
    </Text>
  );

  return (
    <Stack gap="sm" w={320}>
      <Group gap="sm" align="center" wrap="wrap">
        {nameNode}
        {showFullCard && (
          <AiContentBadge content={aiContent} reasoning={aiReasoning} variant="outline" />
        )}
        <ArtistPreferenceButtons artistId={artistId} current={preference} size="sm" />
      </Group>
      {showFullCard && (info?.country || info?.active_since != null) && (
        <Group gap="xs">
          {info?.country && (
            <Text size="sm">
              {countryFlag(info.country)} {info.country}
            </Text>
          )}
          {info?.active_since != null && (
            <Text size="sm" c="dimmed">
              · {t('library.detail.active_since', { year: info.active_since })}
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
      {showFullCard && collaborators.length > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600} c="dimmed">
            {t('library.detail.notable_collaborators')}
          </Text>
          <Text size="sm">{collaborators.join(', ')}</Text>
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

- [ ] **Step 6: Run the test to verify it passes**

Run: `pnpm test src/features/library/components/__tests__/ArtistTile.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 7: Typecheck + library suite**

Run: `pnpm typecheck`
Expected: 0 errors (confirms `ArtistDetailHeader` still compiles after the badge refactor).
Run: `pnpm test src/features/library`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/library/lib/aiContent.tsx \
        frontend/src/features/library/components/ArtistTile.tsx \
        frontend/src/features/library/components/__tests__/ArtistTile.test.tsx \
        frontend/src/features/library/components/ArtistDetailHeader.tsx
git commit -m "feat(library): add ArtistTile and shared AI-content badge"
```

---

## Task 4: `ArtistsPanel` (main tile + expandable chips)

**Files:**
- Create: `frontend/src/features/library/components/ArtistsPanel.tsx`
- Modify: `frontend/src/i18n/en.json`
- Test: `frontend/src/features/library/components/__tests__/ArtistsPanel.test.tsx`

- [ ] **Step 1: Add i18n keys for the panel**

In `frontend/src/i18n/en.json`, add a `library.artists_panel` block (place it after the `library.tile` block):

```json
    "artists_panel": {
      "heading": "Artists",
      "expand_aria": "Show {{name}} details"
    },
```

- [ ] **Step 2: Write the failing test for `ArtistsPanel`**

Create `frontend/src/features/library/components/__tests__/ArtistsPanel.test.tsx`:

```tsx
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { ArtistsPanel } from '../ArtistsPanel';
import * as client from '../../../../api/client';

function renderPanel(artists: { id: string; name: string; role?: string }[], styleId?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistsPanel artists={artists} styleId={styleId} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistsPanel', () => {
  beforeEach(() => vi.restoreAllMocks());

  test('renders nothing when there are no artists', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    const { container } = renderPanel([]);
    expect(container).toBeEmptyDOMElement();
  });

  test('first artist is the main tile; the rest are chips', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderPanel(
      [
        { id: 'a1', name: 'Main Artist', role: 'main' },
        { id: 'a2', name: 'Second', role: 'main' },
        { id: 'a3', name: 'Third', role: 'main' },
      ],
      'techno',
    );
    // Main artist name rendered (tile shows the fallback name immediately).
    expect(screen.getByText('Main Artist')).toBeInTheDocument();
    // Others appear as chip buttons.
    expect(screen.getByRole('button', { name: 'Show Second details' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show Third details' })).toBeInTheDocument();
  });

  test('clicking a chip expands it to a tile for that artist', async () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    const user = userEvent.setup();
    renderPanel(
      [
        { id: 'a1', name: 'Main Artist' },
        { id: 'a2', name: 'Second' },
      ],
      'techno',
    );
    await user.click(screen.getByRole('button', { name: 'Show Second details' }));
    // After expand, the chip is replaced by a tile whose name links to the artist.
    expect(await screen.findByRole('link', { name: 'Second' })).toHaveAttribute(
      'href',
      '/library/techno/artists/a2',
    );
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pnpm test src/features/library/components/__tests__/ArtistsPanel.test.tsx`
Expected: FAIL — `Cannot find module '../ArtistsPanel'`.

- [ ] **Step 4: Implement `ArtistsPanel`**

Create `frontend/src/features/library/components/ArtistsPanel.tsx`. The main artist (`artists[0]`) always renders as a full `ArtistTile`. Every other artist renders as a compact chip that expands, on click, into its own `ArtistTile` (lazy — its `useArtistInfo` fires only once mounted, avoiding a fetch storm):

```tsx
import { useState } from 'react';
import { Badge, Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ArtistTile } from './ArtistTile';

export interface PanelArtist {
  id: string;
  name: string;
  role?: string;
}

interface Props {
  artists: ReadonlyArray<PanelArtist>;
  /** Present on bucket/category players; absent on playlists (no style context). */
  styleId?: string;
}

export function ArtistsPanel({ artists, styleId }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  if (artists.length === 0) return null;

  const [main, ...others] = artists;

  const expand = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });

  return (
    <Stack gap="sm">
      <Text fw={600} size="sm">
        {t('library.artists_panel.heading')}
      </Text>
      <ArtistTile artistId={main.id} artistName={main.name} styleId={styleId} />
      {others.length > 0 && (
        <Stack gap="xs">
          {others.map((a) =>
            expanded.has(a.id) ? (
              <ArtistTile key={a.id} artistId={a.id} artistName={a.name} styleId={styleId} />
            ) : (
              <Badge
                key={a.id}
                component="button"
                type="button"
                variant="light"
                size="lg"
                style={{ cursor: 'pointer' }}
                onClick={() => expand(a.id)}
                aria-label={t('library.artists_panel.expand_aria', { name: a.name })}
              >
                {a.name}
                {a.role && a.role !== 'main' ? ` · ${a.role}` : ''}
              </Badge>
            ),
          )}
        </Stack>
      )}
    </Stack>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pnpm test src/features/library/components/__tests__/ArtistsPanel.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 6: Typecheck**

Run: `pnpm typecheck`
Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/library/components/ArtistsPanel.tsx \
        frontend/src/features/library/components/__tests__/ArtistsPanel.test.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(library): add ArtistsPanel with main tile and expandable chips"
```

---

## Task 5: Render `ArtistsPanel` on the three players

**Files:**
- Modify: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`
- Modify: `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.artists.test.tsx`

This task wires the panel below the existing label block on each player, sourcing artists from the per-player `effectiveRich` track. `BucketTrack.artists` already carries `{id,name,role}`; `CategoryTrack.artists` and `PlaylistTrack.artists` carry `{id,name}` (role omitted → chips show no role suffix, which is correct since all roles are `main` today).

- [ ] **Step 1: Write a failing integration test for the bucket player**

Create `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.artists.test.tsx`. This asserts that, given a playing bucket track with multiple artists, the panel renders the main artist tile + chips. Mock the playback + triage-block hooks so the panel reaches its rendered state:

```tsx
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import type { BucketTrack } from '../../hooks/useBucketTracks';
import * as client from '../../../../api/client';

// Playback: report a current track so the panel renders its body.
vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    track: { current: { id: 't1', title: 'Song', artists: '', cover_url: null, duration_ms: 1, spotify_id: null }, positionMs: 0 },
    queue: { status: 'playing', source: { type: 'bucket', blockId: 'b1', bucketId: 'k1' } },
    sdk: { error: null },
    devices: { active: null, cloderTabId: null, open: () => {} },
    controls: {
      togglePlayPause: () => {}, prev: () => {}, next: () => {}, play: () => {},
      seekMs: () => {}, seekPct: () => {}, positionMs: 0,
    },
  }),
}));
vi.mock('../../../playback/usePlaybackHotkeys', () => ({ usePlaybackHotkeys: () => {} }));
vi.mock('../../hooks/useTriageBlock', () => ({
  useTriageBlock: () => ({ data: { style_id: 'techno', status: 'DONE', buckets: [] } }),
}));
vi.mock('../../hooks/useBucketDistribute', () => ({ useBucketDistribute: () => () => {} }));

import { BucketPlayerPanel } from '../BucketPlayerPanel';

const track: BucketTrack = {
  track_id: 't1', title: 'Song', mix_name: null, isrc: null, bpm: 128, length_ms: 1000,
  publish_date: null, spotify_release_date: null, spotify_id: null, release_type: null,
  is_ai_suspected: false,
  artists: [
    { id: 'a1', name: 'Main Artist', role: 'main' },
    { id: 'a2', name: 'Second', role: 'main' },
  ],
  label_id: 'l1', label_name: 'Label', added_at: '2026-01-01',
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <BucketPlayerPanel blockId="b1" bucketId="k1" items={[track]} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('BucketPlayerPanel — artists', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
  });

  test('renders the main artist tile and a chip for the second artist', () => {
    renderPanel();
    expect(screen.getByText('Main Artist')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show Second details' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.artists.test.tsx`
Expected: FAIL — no "Show Second details" button (panel not wired yet).

- [ ] **Step 3: Wire `ArtistsPanel` into `BucketPlayerPanel`**

In `frontend/src/features/triage/components/BucketPlayerPanel.tsx`, add the import beside the `LabelTile` import:

```tsx
import { ArtistsPanel } from '../../library/components/ArtistsPanel';
```

Render the panel immediately after the existing `<LabelTile … />` (inside the returned `Stack`, still before its closing tag):

```tsx
      <LabelTile
        labelId={effectiveRich?.label_id ?? null}
        labelName={effectiveRich?.label_name ?? null}
        styleId={block?.style_id ?? ''}
      />
      <ArtistsPanel artists={effectiveRich?.artists ?? []} styleId={block?.style_id ?? ''} />
```

- [ ] **Step 4: Run the bucket test to verify it passes**

Run: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.artists.test.tsx`
Expected: PASS.

- [ ] **Step 5: Wire `ArtistsPanel` into `CategoryPlayerPanel`**

In `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`, add the import beside the `LabelTile` import:

```tsx
import { ArtistsPanel } from '../../library/components/ArtistsPanel';
```

The category panel already renders `LabelTile` conditionally at the end of its `Stack`. Add the artists panel right after that block (it has the `styleId` prop in scope and `effectiveRich.artists` is `{id,name}[]`):

```tsx
      {effectiveRich?.label?.id && (
        <LabelTile
          labelId={effectiveRich.label.id}
          labelName={effectiveRich.label.name ?? null}
          styleId={styleId}
        />
      )}
      <ArtistsPanel artists={effectiveRich?.artists ?? []} styleId={styleId} />
```

- [ ] **Step 6: Wire `ArtistsPanel` into `PlaylistPlayerPanel`**

In `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx`, add the import:

```tsx
import { ArtistsPanel } from '../../library/components/ArtistsPanel';
```

The playlist panel ends with a `PlayerPanelTagCloud` followed by a comment explaining why it omits `LabelTile` (no styleId). Add the artists panel after that tag cloud — **no `styleId`** (playlist tracks have none → `ArtistTile` renders names as plain text, per Task 3):

```tsx
      <PlayerPanelTagCloud
        trackId={current.id}
        assignedTagIds={assignedTagIds}
        onAdd={(id) => void onAddTag(id)}
        onRemove={(id) => void onRemoveTag(id)}
      />
      <ArtistsPanel artists={effectiveRich?.artists ?? []} />
```

- [ ] **Step 7: Run the affected player suites + typecheck**

Run: `pnpm test src/features/triage src/features/categories src/features/playlists`
Expected: PASS (existing player tests + the new bucket artists test).
Run: `pnpm typecheck`
Expected: 0 errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/triage/components/BucketPlayerPanel.tsx \
        frontend/src/features/triage/components/__tests__/BucketPlayerPanel.artists.test.tsx \
        frontend/src/features/categories/components/CategoryPlayerPanel.tsx \
        frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx
git commit -m "feat(players): show artist info panel on bucket, category, and playlist players"
```

---

## Task 6: Browser test for `ArtistsPanel` layout

**Files:**
- Test: `frontend/src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx`

jsdom applies no stylesheets, so the panel's visual layout (main tile stacked above the chip row, chips laid out horizontally, tile width) must be verified in a real browser (CLAUDE.md gotcha #11). This test runs only under `pnpm test:browser` (it is excluded from `pnpm test`/CI).

- [ ] **Step 1: Write the browser test**

Create `frontend/src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx`:

```tsx
/**
 * Browser-mode layout check for ArtistsPanel: the main ArtistTile renders above
 * the chip row, and multiple chips lay out on the same row (horizontal Stack of
 * inline badges wrapping). jsdom can't verify this — no stylesheets — so this
 * lives in the browser harness (Playwright via @vitest/browser).
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { ArtistsPanel } from '../ArtistsPanel';

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistsPanel
            artists={[
              { id: 'a1', name: 'Main Artist' },
              { id: 'a2', name: 'Second' },
              { id: 'a3', name: 'Third' },
            ]}
            styleId="techno"
          />
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe('ArtistsPanel layout (browser)', () => {
  test('chips sit below the main tile and share a row', () => {
    renderPanel();
    const main = screen.getByText('Main Artist').getBoundingClientRect();
    const chip2 = screen.getByRole('button', { name: 'Show Second details' }).getBoundingClientRect();
    const chip3 = screen.getByRole('button', { name: 'Show Third details' }).getBoundingClientRect();

    // Main tile is above the chips.
    expect(chip2.top).toBeGreaterThan(main.top);
    // The two chips share roughly the same row (top within a few px).
    expect(Math.abs(chip2.top - chip3.top)).toBeLessThan(8);
    // Chips are laid out left-to-right.
    expect(chip3.left).toBeGreaterThan(chip2.left);
  });
});
```

> Implementer note: if `render`'s provider nesting above triggers a JSX-closing-tag mismatch in your editor, fix the close order to match the open order (`QueryClientProvider` → `MantineProvider` → `MemoryRouter`). The intent is the three providers wrapping `ArtistsPanel`.

- [ ] **Step 2: Run the browser test**

Run: `pnpm test:browser src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx`
Expected: PASS. If chips don't share a row (e.g. they stack vertically), adjust the chip container in `ArtistsPanel` to a wrapping horizontal group (`<Group gap="xs" wrap="wrap">` instead of `<Stack gap="xs">`) and re-run; update the jsdom test in Task 4 only if the roles/labels change (they shouldn't).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx
git commit -m "test(library): browser layout check for ArtistsPanel"
```

---

## Final verification (after all tasks)

- [ ] Run the full jsdom suite: `pnpm test` → all pass.
- [ ] Run typecheck: `pnpm typecheck` → 0 errors.
- [ ] Run the browser test locally: `pnpm test:browser src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx` → pass.
- [ ] Dispatch the final whole-implementation code review.
- [ ] Use `superpowers:finishing-a-development-branch` to PR all of SP2 (2A + 2B + 2C) — this is the last plan; the PR completes the artist-enrichment feature end to end.

---

## Self-review notes (planner)

- **Spec coverage:** requirement 4 player panel → Tasks 3–5 (`ArtistTile` + `ArtistsPanel` on all 3 players, panel B: main tile + chips); preferences (spec §5) → Tasks 1–2 (hook + buttons + table column + detail header + my-filter), reused in `ArtistTile` (Task 3); AI badge (spec §6) → shared `aiContent.tsx` (Task 3), `variant: outline` on the tile / `colored` on the detail header; testing (spec §testing) → jsdom per task + one browser test (Task 6).
- **No backend touch:** confirmed `my` filter and the preference endpoint already exist in `schema.d.ts` (SP1) — 2C is frontend-only, matching the spec ("the only backend change [bucket-tracks] was in 2A").
- **Panel B "main" selection:** order-based (`artists[0]`), justified by all roles being `"main"` in the data today (`canonicalize.py:415`). Documented in Context fact 4.
- **Playlist no-styleId:** handled by `ArtistTile`'s optional `styleId` (Task 3 fact 6) so the full panel renders on the playlist player without a broken cross-link (spec decision: "Playlist player | Full ArtistsPanel").
- **Type consistency:** `ArtistPreference` (`'liked'|'disliked'|null`) and `PreferenceMutationStatus` (`…|'none'`) defined once in `useSetArtistPreference.ts` and imported by the buttons; `PanelArtist` (`{id,name,role?}`) accepts both the bucket (`role` present) and category/playlist (`role` absent) shapes; `artistInfoKey`/`artistDetailKey`/`['library','artists',…]` keys match the 2A hooks exactly.
