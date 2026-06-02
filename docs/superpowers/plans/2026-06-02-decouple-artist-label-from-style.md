# Decouple artist/label detail pages from style — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make artist and label detail pages canonically addressable at top-level routes (`/artists/:id`, `/labels/:id`) so any context — playlists included — can link to them unconditionally.

**Architecture:** Frontend-only React Router refactor. Detail routes move out from under `/library/:styleId`. The `styleId` prop disappears from every link-builder (tiles, cards, tables, panels); the name always renders as a link to the top-level route. The detail-page "back" link is replaced by a history-based `useBackOrFallback` hook. No backend, API, DB, or OpenAPI change — `GET /artists/{id}` and `GET /labels/{id}` already take only the id.

**Tech Stack:** React 19, react-router (v7 import path `react-router`), Mantine 9, TanStack Query, Vitest + Testing Library, MSW, i18next, pnpm.

**Spec:** `docs/superpowers/specs/2026-06-02-decouple-artist-label-from-style-design.md`

---

## Conventions for every task

- All commands run **from `frontend/`** (worktree path: `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/artist_lable_style_connection/frontend`). `pnpm dev`/tests must not run from repo root (CLAUDE.md gotcha #9).
- Single-file test run: `pnpm exec vitest run <path>`.
- **Commits go through the `caveman:caveman-commit` skill** (CLAUDE.md policy), then `git commit -m "<generated>"`. The suggested message in each Commit step is the intended content — regenerate via the skill if it differs, do not hand-write the subject.
- Branch is already `feat/decouple-artist-label-from-style`.
- **Ordering note (interim runtime state):** Task 2 moves the routes first; Tasks 3–6 then repoint each link source. Between Task 2 and Task 6 some links in the app still point at the old `/library/:styleId/...` path and would 404 at runtime, but each task's own test suite stays green because tile/table tests are updated inside the same task that changes the tile/table. Task 7 verifies the whole flow end-to-end.

---

## File map

**Create**
- `src/features/library/hooks/useBackOrFallback.ts`
- `src/features/library/hooks/__tests__/useBackOrFallback.test.tsx`

**Modify — production**
- `src/routes/router.tsx`
- `src/features/library/routes/ArtistDetailPage.tsx`
- `src/features/library/routes/LabelDetailPage.tsx`
- `src/features/library/components/ArtistDetailHeader.tsx`
- `src/features/library/components/LabelDetailHeader.tsx`
- `src/features/library/components/ArtistTile.tsx`
- `src/features/library/components/LabelTile.tsx`
- `src/features/library/components/ArtistsPanel.tsx`
- `src/features/library/components/ArtistsTable.tsx`
- `src/features/library/components/LabelsTable.tsx`
- `src/features/library/components/ArtistCard.tsx`
- `src/features/library/components/LabelCard.tsx`
- `src/features/library/routes/LibraryListPage.tsx`
- `src/features/library/routes/ArtistsListPage.tsx`
- `src/features/triage/components/BucketPlayerPanel.tsx`
- `src/features/curate/components/CurateSession.tsx`
- `src/features/categories/components/CategoryPlayerPanel.tsx`
- `src/features/admin/components/enrichment/BacklogTable.tsx`
- `src/i18n/en.json`

**Modify — tests**
- `src/features/library/routes/__tests__/ArtistDetailPage.test.tsx`
- `src/features/library/components/__tests__/ArtistTile.test.tsx`
- `src/features/library/components/__tests__/LabelTile.test.tsx`
- `src/features/library/components/__tests__/ArtistsPanel.test.tsx`
- `src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx`
- `src/features/library/components/__tests__/ArtistsTable.preference.test.tsx`
- `src/features/library/components/__tests__/LabelsTable.test.tsx`
- `src/features/library/components/__tests__/LabelCard.test.tsx`
- `src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx`

---

## Task 1: `useBackOrFallback` hook + i18n key

**Files:**
- Create: `src/features/library/hooks/useBackOrFallback.ts`
- Create: `src/features/library/hooks/__tests__/useBackOrFallback.test.tsx`
- Modify: `src/i18n/en.json:902`

- [ ] **Step 1: Write the failing test**

Create `src/features/library/hooks/__tests__/useBackOrFallback.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, Link } from 'react-router';
import { useBackOrFallback } from '../useBackOrFallback';

function Detail() {
  const goBack = useBackOrFallback('/fallback');
  return (
    <button type="button" onClick={goBack}>
      back
    </button>
  );
}

describe('useBackOrFallback', () => {
  it('goes back in history when an in-app entry exists', async () => {
    render(
      <MemoryRouter initialEntries={['/start']}>
        <Routes>
          <Route path="/start" element={<Link to="/detail">go</Link>} />
          <Route path="/detail" element={<Detail />} />
          <Route path="/fallback" element={<div>FALLBACK</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByText('go')); // /start -> /detail
    await userEvent.click(screen.getByText('back')); // back -> /start
    expect(screen.getByText('go')).toBeInTheDocument();
  });

  it('navigates to fallback when there is no history (deep-link)', async () => {
    render(
      <MemoryRouter initialEntries={['/detail']}>
        <Routes>
          <Route path="/detail" element={<Detail />} />
          <Route path="/fallback" element={<div>FALLBACK</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByText('back'));
    expect(screen.getByText('FALLBACK')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/features/library/hooks/__tests__/useBackOrFallback.test.tsx`
Expected: FAIL — `Failed to resolve import "../useBackOrFallback"`.

- [ ] **Step 3: Create the hook**

Create `src/features/library/hooks/useBackOrFallback.ts`:

```ts
import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router';

/**
 * Returns a handler that goes back one history entry when in-app history
 * exists, otherwise navigates to `fallback`. react-router sets
 * `location.key === 'default'` only for the first/only entry (deep-link or
 * fresh tab) where there is nothing to go back to.
 */
export function useBackOrFallback(fallback: string): () => void {
  const navigate = useNavigate();
  const location = useLocation();
  return useCallback(() => {
    if (location.key !== 'default') {
      navigate(-1);
    } else {
      navigate(fallback);
    }
  }, [navigate, location.key, fallback]);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm exec vitest run src/features/library/hooks/__tests__/useBackOrFallback.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Add the i18n key**

In `src/i18n/en.json`, the library `detail` block (around line 901), replace:

```json
      "back_to_list": "Back to {{style}}",
```

with:

```json
      "back": "← Back",
```

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/features/library/hooks/useBackOrFallback.ts \
  src/features/library/hooks/__tests__/useBackOrFallback.test.tsx \
  src/i18n/en.json
git commit -m "feat(library): add useBackOrFallback hook + back i18n key"
```

---

## Task 2: Move detail routes to top-level; drop styleId from detail pages + headers

**Files:**
- Modify: `src/routes/router.tsx:98-103`
- Modify: `src/features/library/routes/ArtistDetailPage.tsx`
- Modify: `src/features/library/routes/LabelDetailPage.tsx`
- Modify: `src/features/library/components/ArtistDetailHeader.tsx`
- Modify: `src/features/library/components/LabelDetailHeader.tsx`
- Test: `src/features/library/routes/__tests__/ArtistDetailPage.test.tsx`

- [ ] **Step 1: Update the failing test first (route + back control)**

In `src/features/library/routes/__tests__/ArtistDetailPage.test.tsx`, change `renderPage` to mount the page at the new top-level route and provide a `/library` landing for the back button. Replace the `MemoryRouter`/`Routes` block (lines 62-69) with:

```tsx
            <MemoryRouter initialEntries={['/artists/artist-1']}>
              <Routes>
                <Route path="/artists/:artistId" element={<ArtistDetailPage />} />
                <Route path="/library" element={<div>LIBRARY</div>} />
              </Routes>
            </MemoryRouter>
```

Then add this test inside the `describe` block (after the existing `renders the artist name` test):

```tsx
  it('renders a back control', () => {
    renderPage();
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/features/library/routes/__tests__/ArtistDetailPage.test.tsx`
Expected: FAIL — the page still reads `styleId` from params and renders the old `back_to_list` anchor (a link, not a button), so `getByRole('button', { name: /back/i })` finds nothing; the `Navigate` guard may also redirect.

- [ ] **Step 3: Update the router**

In `src/routes/router.tsx`, the `library` block currently is (lines 94-103):

```tsx
      {
        path: 'library',
        children: [
          { index: true, element: <LibraryIndexRedirect /> },
          { path: ':styleId', element: <LibraryListPage /> },
          { path: ':styleId/labels/:labelId', element: <LabelDetailPage /> },
          { path: ':styleId/artists', element: <ArtistsListPage /> },
          { path: ':styleId/artists/:artistId', element: <ArtistDetailPage /> },
        ],
      },
```

Replace it with (remove the two detail routes from `library`, add two top-level routes after the block):

```tsx
      {
        path: 'library',
        children: [
          { index: true, element: <LibraryIndexRedirect /> },
          { path: ':styleId', element: <LibraryListPage /> },
          { path: ':styleId/artists', element: <ArtistsListPage /> },
        ],
      },
      { path: 'artists/:artistId', element: <ArtistDetailPage /> },
      { path: 'labels/:labelId', element: <LabelDetailPage /> },
```

(The `ArtistDetailPage` / `LabelDetailPage` imports on line 39 stay.)

- [ ] **Step 4: Update `ArtistDetailPage.tsx`**

Replace lines 13-16:

```tsx
  const { t } = useTranslation();
  const { styleId, artistId } = useParams<{ styleId: string; artistId: string }>();
  const query = useArtistDetail(artistId ?? null);
  if (!styleId || !artistId) return <Navigate to="/library" replace />;
```

with:

```tsx
  const { t } = useTranslation();
  const { artistId } = useParams<{ artistId: string }>();
  const query = useArtistDetail(artistId ?? null);
  if (!artistId) return <Navigate to="/library" replace />;
```

And the header usage (line 41):

```tsx
            <ArtistDetailHeader info={info} artistId={artistId} />
```

- [ ] **Step 5: Update `LabelDetailPage.tsx`**

Replace lines 13-16:

```tsx
  const { t } = useTranslation();
  const { styleId, labelId } = useParams<{ styleId: string; labelId: string }>();
  const query = useLabelDetail(labelId ?? null);
  if (!styleId || !labelId) return <Navigate to="/library" replace />;
```

with:

```tsx
  const { t } = useTranslation();
  const { labelId } = useParams<{ labelId: string }>();
  const query = useLabelDetail(labelId ?? null);
  if (!labelId) return <Navigate to="/library" replace />;
```

And the header usage (line 41):

```tsx
            <LabelDetailHeader info={info} labelId={labelId} />
```

- [ ] **Step 6: Update `ArtistDetailHeader.tsx`**

Change the imports (lines 1-2) — drop `Link`, add the hook:

```tsx
import { Group, Title, Text, Anchor, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useBackOrFallback } from '../hooks/useBackOrFallback';
```

Change the Props (lines 11-15) — drop `styleId`:

```tsx
interface Props {
  info: ArtistDetail;
  artistId: string;
}
```

Change the signature (line 17) and add the handler right after the existing `const { t } = useTranslation();`:

```tsx
export function ArtistDetailHeader({ info, artistId }: Props) {
  const { t } = useTranslation();
  const goBack = useBackOrFallback('/library');
```

Replace the back anchor (lines 37-39):

```tsx
      <Anchor component="button" type="button" onClick={goBack} size="sm">
        {t('library.detail.back')}
      </Anchor>
```

- [ ] **Step 7: Update `LabelDetailHeader.tsx`**

Change the imports (lines 1-2) — drop `Link`, add the hook:

```tsx
import { Group, Title, Text, Anchor, Badge, Tooltip, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useBackOrFallback } from '../hooks/useBackOrFallback';
```

Change the Props (lines 10-14) — drop `styleId`:

```tsx
interface Props {
  info: LabelDetail;
  labelId: string;
}
```

Change the signature (line 27) and add the handler after `const { t } = useTranslation();`:

```tsx
export function LabelDetailHeader({ info, labelId }: Props) {
  const { t } = useTranslation();
  const goBack = useBackOrFallback('/library');
```

Replace the back anchor (lines 75-77):

```tsx
      <Anchor component="button" type="button" onClick={goBack} size="sm">
        {t('library.detail.back')}
      </Anchor>
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `pnpm exec vitest run src/features/library/routes/__tests__/ArtistDetailPage.test.tsx`
Expected: PASS (all tests, including `renders a back control`).

- [ ] **Step 9: Typecheck**

Run: `pnpm typecheck`
Expected: PASS. (Tiles/tables still emit old href strings — that is not a type error; their props are unchanged in this task.)

- [ ] **Step 10: Commit**

```bash
cd frontend && git add src/routes/router.tsx \
  src/features/library/routes/ArtistDetailPage.tsx \
  src/features/library/routes/LabelDetailPage.tsx \
  src/features/library/components/ArtistDetailHeader.tsx \
  src/features/library/components/LabelDetailHeader.tsx \
  src/features/library/routes/__tests__/ArtistDetailPage.test.tsx
git commit -m "$(cat <<'EOF'
feat(library): move artist/label detail to top-level routes

Detail pages now live at /artists/:id and /labels/:id instead of
under /library/:styleId. styleId is dropped from the pages and
headers; the back link uses useBackOrFallback (history, fallback
/library) since there is no style context off the library list.
EOF
)"
```

---

## Task 3: ArtistTile + ArtistsPanel — always link to `/artists/:id`

**Files:**
- Modify: `src/features/library/components/ArtistTile.tsx`
- Modify: `src/features/library/components/ArtistsPanel.tsx`
- Modify: `src/features/triage/components/BucketPlayerPanel.tsx:165`
- Modify: `src/features/curate/components/CurateSession.tsx:356-359`
- Modify: `src/features/categories/components/CategoryPlayerPanel.tsx:291`
- Test: `src/features/library/components/__tests__/ArtistTile.test.tsx`
- Test: `src/features/library/components/__tests__/ArtistsPanel.test.tsx`
- Test: `src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx`

- [ ] **Step 1: Update `ArtistTile.test.tsx` (new expectations first)**

Replace the whole file body of the `describe` block plus `renderTile` signature so `styleId` is gone and the name is always a link to `/artists/:id`. Replace lines 10 and 33-59 as follows.

Line 10 (drop `styleId` from the helper):

```tsx
function renderTile(props: { artistId: string | null; artistName?: string }, seed?: unknown) {
```

Replace the two style-dependent tests (lines 33-59) with:

```tsx
  test('renders enriched info: name links to the top-level artist page', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderTile(
      { artistId: 'a1', artistName: 'A1' },
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
    expect(link).toHaveAttribute('href', '/artists/a1');
    expect(screen.getByText('Pioneer.')).toBeInTheDocument();
    expect(screen.getByText('AI CONFIRMED')).toBeInTheDocument();
  });

  test('renders the name as a link even in minimal mode', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderTile({ artistId: 'a1', artistName: 'A1' }, { artist_name: 'NoStyle', my_preference: null });
    expect(screen.getByRole('link', { name: 'NoStyle' })).toHaveAttribute('href', '/artists/a1');
  });
```

- [ ] **Step 2: Update `ArtistsPanel.test.tsx` (new expectations)**

Line 10 — drop `styleId` param:

```tsx
function renderPanel(artists: { id: string; name: string; role?: string }[]) {
```

Line 16 — drop the prop:

```tsx
          <ArtistsPanel artists={artists} />
```

Remove the now-extra `'techno'` argument in the two `renderPanel(...)` calls (lines 36-43 and 52-58) — call `renderPanel([...])` with the array only. Then update the expanded-chip href assertion (lines 60-63):

```tsx
    expect(await screen.findByRole('link', { name: 'Second' })).toHaveAttribute(
      'href',
      '/artists/a2',
    );
```

- [ ] **Step 3: Update `ArtistsPanel.browser.test.tsx`**

Remove the `styleId="techno"` prop (line 27) so the render is:

```tsx
          <ArtistsPanel
            artists={[
              { id: 'a1', name: 'Main Artist' },
              { id: 'a2', name: 'Second' },
              { id: 'a3', name: 'Third' },
            ]}
          />
```

- [ ] **Step 4: Run the three tests to verify they fail**

Run:
```
pnpm exec vitest run src/features/library/components/__tests__/ArtistTile.test.tsx src/features/library/components/__tests__/ArtistsPanel.test.tsx
```
Expected: FAIL — current `ArtistTile` renders plain `<Text>` when no `styleId`, and the link (when present) points to `/library/.../artists/...`, so the new `/artists/a1` / `/artists/a2` assertions fail. (The browser test runs under `pnpm test:browser`; it will still compile but is verified in Task 7.)

- [ ] **Step 5: Update `ArtistTile.tsx`**

Remove the `styleId` field + comment from `Props` (lines 12-14) so it reads:

```tsx
interface Props {
  artistId: string | null | undefined;
  artistName?: string | null | undefined;
}
```

Change the signature (line 34):

```tsx
export function ArtistTile({ artistId, artistName }: Props) {
```

Replace the `nameNode` ternary (lines 67-75) with an unconditional link:

```tsx
  const nameNode = (
    <Anchor component={Link} to={`/artists/${artistId}`} fw={600} size="lg">
      {displayName || artistId}
    </Anchor>
  );
```

(`Anchor`, `Link`, and `Text` imports stay — `Text` is still used in the country/active-since rows below.)

- [ ] **Step 6: Update `ArtistsPanel.tsx`**

Remove the `styleId` field + comment from `Props` (lines 13-15):

```tsx
interface Props {
  artists: ReadonlyArray<PanelArtist>;
}
```

Change the signature (line 18):

```tsx
export function ArtistsPanel({ artists }: Props) {
```

Drop `styleId={styleId}` from both `<ArtistTile>` usages (lines 40 and 45):

```tsx
      <ArtistTile artistId={main.id} artistName={main.name} />
```
```tsx
              <ArtistTile key={a.id} artistId={a.id} artistName={a.name} />
```

- [ ] **Step 7: Drop the now-invalid `styleId` prop from the three player panels**

`src/features/triage/components/BucketPlayerPanel.tsx` line 165 — change to:

```tsx
      <ArtistsPanel artists={effectiveRich?.artists ?? []} />
```

`src/features/curate/components/CurateSession.tsx` lines 356-359 — change to:

```tsx
        <ArtistsPanel
          artists={session.currentTrack?.artists ?? []}
        />
```

`src/features/categories/components/CategoryPlayerPanel.tsx` line 291 — change to:

```tsx
      <ArtistsPanel artists={effectiveRich?.artists ?? []} />
```

- [ ] **Step 8: Run the tests + typecheck to verify pass**

Run:
```
pnpm exec vitest run src/features/library/components/__tests__/ArtistTile.test.tsx src/features/library/components/__tests__/ArtistsPanel.test.tsx
pnpm typecheck
```
Expected: PASS. Typecheck clean (no remaining `styleId` passed to `ArtistTile`/`ArtistsPanel`).

- [ ] **Step 9: Commit**

```bash
cd frontend && git add src/features/library/components/ArtistTile.tsx \
  src/features/library/components/ArtistsPanel.tsx \
  src/features/triage/components/BucketPlayerPanel.tsx \
  src/features/curate/components/CurateSession.tsx \
  src/features/categories/components/CategoryPlayerPanel.tsx \
  src/features/library/components/__tests__/ArtistTile.test.tsx \
  src/features/library/components/__tests__/ArtistsPanel.test.tsx \
  src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx
git commit -m "feat(library): ArtistTile always links to /artists/:id"
```

---

## Task 4: LabelTile — always link to `/labels/:id`

**Files:**
- Modify: `src/features/library/components/LabelTile.tsx`
- Modify: `src/features/triage/components/BucketPlayerPanel.tsx:160-164`
- Modify: `src/features/curate/components/CurateSession.tsx:351-355`
- Modify: `src/features/categories/components/CategoryPlayerPanel.tsx:285-289`
- Test: `src/features/library/components/__tests__/LabelTile.test.tsx`
- Test: `src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx`

- [ ] **Step 1: Rewrite `LabelTile.test.tsx` (new expectations first)**

The two `styleId`-specific tests collapse into "always a link". Replace the whole file with:

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
            <LabelTile labelId={labelId} labelName={labelName} />
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
    expect(screen.getByRole('button', { name: /^like label$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^dislike label$/i })).toBeInTheDocument();
    expect(screen.queryByText('soulful d&b')).not.toBeInTheDocument();
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

  it('renders the label name as a link to the top-level label page', async () => {
    server.use(
      http.get('http://localhost/labels/linked', () =>
        HttpResponse.json({ label_name: 'Linked', my_preference: null }),
      ),
    );
    renderTile('linked', 'fallback');
    await waitFor(() => expect(screen.getByText('Linked')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'Linked' })).toHaveAttribute('href', '/labels/linked');
  });
});
```

- [ ] **Step 2: Update `PlaylistPlayerPanel.test.tsx` (invert the no-link test)**

Replace the test at lines 181-196 (`renders LabelTile with label name as plain text (no link)`) with:

```tsx
  it('renders the LabelTile label name as a link to the label page', async () => {
    const fokuzTrack: PlaylistTrack = {
      ...seedTrack,
      label: { id: 'lbl-1', name: 'Fokuz Recordings' },
    };
    server.use(
      http.get('http://localhost/labels/lbl-1', () =>
        HttpResponse.json({ label_name: 'Fokuz Recordings', my_preference: null }),
      ),
    );
    render(ui([fokuzTrack]));
    const link = await screen.findByRole('link', { name: 'Fokuz Recordings' });
    expect(link).toHaveAttribute('href', '/labels/lbl-1');
  });
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:
```
pnpm exec vitest run src/features/library/components/__tests__/LabelTile.test.tsx src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx
```
Expected: FAIL — `LabelTile` currently renders plain `<Text>` without `styleId` (no link), so both the `/labels/linked` and `/labels/lbl-1` link assertions fail.

- [ ] **Step 4: Update `LabelTile.tsx`**

Remove the `styleId` field + comment from `Props` (lines 12-13) so it reads:

```tsx
interface Props {
  labelId: string | null | undefined;
  labelName?: string | null | undefined;
}
```

Change the signature (line 32):

```tsx
export function LabelTile({ labelId, labelName }: Props) {
```

Replace the name ternary (lines 71-79) with an unconditional link:

```tsx
        <Anchor component={Link} to={`/labels/${labelId}`} fw={600} size="lg">
          {displayName || labelId}
        </Anchor>
```

(`Anchor`, `Link`, `Text` imports stay — `Text` is still used in the rich-content rows.)

- [ ] **Step 5: Drop the `styleId` prop from the three player panels' `<LabelTile>`**

`src/features/triage/components/BucketPlayerPanel.tsx` lines 160-164:

```tsx
      <LabelTile
        labelId={effectiveRich?.label_id ?? null}
        labelName={effectiveRich?.label_name ?? null}
      />
```

`src/features/curate/components/CurateSession.tsx` lines 351-355:

```tsx
        <LabelTile
          labelId={session.currentTrack?.label_id ?? null}
          labelName={session.currentTrack?.label_name ?? null}
        />
```

`src/features/categories/components/CategoryPlayerPanel.tsx` lines 285-289:

```tsx
        <LabelTile
          labelId={effectiveRich.label.id}
          labelName={effectiveRich.label.name ?? null}
        />
```

- [ ] **Step 6: Run the tests + typecheck to verify pass**

Run:
```
pnpm exec vitest run src/features/library/components/__tests__/LabelTile.test.tsx src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx
pnpm typecheck
```
Expected: PASS. Typecheck clean.

- [ ] **Step 7: Commit**

```bash
cd frontend && git add src/features/library/components/LabelTile.tsx \
  src/features/triage/components/BucketPlayerPanel.tsx \
  src/features/curate/components/CurateSession.tsx \
  src/features/categories/components/CategoryPlayerPanel.tsx \
  src/features/library/components/__tests__/LabelTile.test.tsx \
  src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx
git commit -m "feat(library): LabelTile always links to /labels/:id"
```

---

## Task 5: Tables — top-level links; drop styleId prop

**Files:**
- Modify: `src/features/library/components/ArtistsTable.tsx:17-24,62`
- Modify: `src/features/library/components/LabelsTable.tsx:17-24,66`
- Modify: `src/features/library/routes/ArtistsListPage.tsx:97-104`
- Modify: `src/features/library/routes/LibraryListPage.tsx:96-103`
- Test: `src/features/library/components/__tests__/ArtistsTable.preference.test.tsx:15-22`
- Test: `src/features/library/components/__tests__/LabelsTable.test.tsx:19-26`

- [ ] **Step 1: Update both table tests first (remove styleId prop)**

In `ArtistsTable.preference.test.tsx`, remove `styleId="techno"` (line 17) from the `<ArtistsTable>` render so the props are `items`, `isLoading`, `page`, `pageCount`, `onPageChange`.

In `LabelsTable.test.tsx`, remove `styleId="dnb"` (line 21) from the `<LabelsTable>` render.

- [ ] **Step 2: Run to verify failure**

Run:
```
pnpm typecheck
```
Expected: FAIL — at this point the tables still declare `styleId: string` as a required prop, so the tests (and the list-page callers) fail typecheck where the prop was removed. (This is the red state for a type-level refactor.)

- [ ] **Step 3: Update `ArtistsTable.tsx`**

Remove `styleId: string;` from `Props` (line 19). Change the name link (line 62):

```tsx
                  <Anchor component={Link} to={`/artists/${it.id}`} fw={500}>
```

- [ ] **Step 4: Update `LabelsTable.tsx`**

Remove `styleId: string;` from `Props` (line 19). Change the name link (line 66):

```tsx
                  <Anchor component={Link} to={`/labels/${it.id}`} fw={500}>
```

- [ ] **Step 5: Update the list-page callers**

`src/features/library/routes/ArtistsListPage.tsx` — remove the `styleId={styleId}` line (line 99) from `<ArtistsTable>`. Keep the page's own `styleId` variable (still used for fetching/tabs).

`src/features/library/routes/LibraryListPage.tsx` — remove the `styleId={styleId}` line (line 98) from `<LabelsTable>`.

- [ ] **Step 6: Run tests + typecheck to verify pass**

Run:
```
pnpm exec vitest run src/features/library/components/__tests__/ArtistsTable.preference.test.tsx src/features/library/components/__tests__/LabelsTable.test.tsx
pnpm typecheck
```
Expected: PASS. Typecheck clean.

- [ ] **Step 7: Commit**

```bash
cd frontend && git add src/features/library/components/ArtistsTable.tsx \
  src/features/library/components/LabelsTable.tsx \
  src/features/library/routes/ArtistsListPage.tsx \
  src/features/library/routes/LibraryListPage.tsx \
  src/features/library/components/__tests__/ArtistsTable.preference.test.tsx \
  src/features/library/components/__tests__/LabelsTable.test.tsx
git commit -m "feat(library): list tables link to top-level entity pages"
```

---

## Task 6: Cards + admin backlog — top-level links

**Files:**
- Modify: `src/features/library/components/ArtistCard.tsx:8-13,23`
- Modify: `src/features/library/components/LabelCard.tsx:8-13,23`
- Modify: `src/features/admin/components/enrichment/BacklogTable.tsx:52`
- Test: `src/features/library/components/__tests__/LabelCard.test.tsx:24-32`

Note: `ArtistCard`/`LabelCard` have no production call sites (verified — no `<ArtistCard`/`<LabelCard` outside tests). Update them for consistency so they never point at a removed route. `ArtistCard` has no test; `LabelCard` does. `BacklogTable`'s test (`AdminArtistEnrichmentBacklogPage.test.tsx`) asserts no `/library/` href, so it needs no change.

- [ ] **Step 1: Update `LabelCard.test.tsx` first (remove styleId prop)**

Change the render (line 28):

```tsx
        <MemoryRouter><LabelCard item={item} /></MemoryRouter>
```

- [ ] **Step 2: Run to verify failure**

Run: `pnpm typecheck`
Expected: FAIL — `LabelCard` still requires the `styleId` prop.

- [ ] **Step 3: Update `LabelCard.tsx`**

Remove `styleId: string;` from `Props` (line 10). Change the signature (line 13) to `export function LabelCard({ item }: Props) {`. Change the link (line 23):

```tsx
      to={`/labels/${item.id}`}
```

- [ ] **Step 4: Update `ArtistCard.tsx`**

Remove `styleId: string;` from `Props` (line 10). Change the signature (line 13) to `export function ArtistCard({ item }: Props) {`. Change the link (line 23):

```tsx
      to={`/artists/${item.id}`}
```

- [ ] **Step 5: Update `BacklogTable.tsx`**

Change the label link (line 52):

```tsx
              <Anchor component={Link} to={`/labels/${row.id}`}>
```

- [ ] **Step 6: Run test + typecheck to verify pass**

Run:
```
pnpm exec vitest run src/features/library/components/__tests__/LabelCard.test.tsx
pnpm typecheck
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd frontend && git add src/features/library/components/ArtistCard.tsx \
  src/features/library/components/LabelCard.tsx \
  src/features/admin/components/enrichment/BacklogTable.tsx \
  src/features/library/components/__tests__/LabelCard.test.tsx
git commit -m "feat(library): cards + admin backlog link to top-level pages"
```

---

## Task 7: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Full typecheck**

Run: `pnpm typecheck`
Expected: PASS, no errors.

- [ ] **Step 2: Lint (catches any now-unused `styleId` variables)**

Run: `pnpm lint`
Expected: PASS. If lint flags an unused `styleId` (e.g. in `CurateSession.tsx` if its only uses were the dropped props), remove the dead declaration, re-run lint, and amend the relevant task's commit or add a fixup commit:

```bash
cd frontend && git commit -am "refactor(library): drop unused styleId after decouple"
```

- [ ] **Step 3: Full jsdom test suite**

Run: `pnpm test`
Expected: PASS. Grep the output for any test still referencing `/library/:styleId/artists/` or `/library/:styleId/labels/` — there should be none.

- [ ] **Step 4: Browser tests (stylesheets + layout)**

Run: `pnpm test:browser`
Expected: PASS — `ArtistsPanel.browser.test.tsx` still verifies the chip layout (it no longer passes `styleId`).

- [ ] **Step 5: Manual browser smoke (CLAUDE.md gotcha #11 + memory: verify visual in browser)**

From `frontend/` with `.env.local` set, run `pnpm dev` and confirm:
- On a playlist player panel, the artist name and label name are now clickable links that navigate to `/artists/:id` and `/labels/:id`.
- On a standalone detail page, the "← Back" control returns to the previous page; opening `/artists/:id` directly in a fresh tab and clicking back lands on `/library`.
- From the library list, clicking an artist/label row still opens the detail page (now at the top-level URL).

- [ ] **Step 6: Finish the branch**

Use `superpowers:finishing-a-development-branch` to open the PR (title + body via `caveman:caveman-commit` per CLAUDE.md policy).

---

## Self-review

**Spec coverage:**
- Routing change (`/artists/:id`, `/labels/:id`) → Task 2.
- Detail pages drop styleId → Task 2.
- Back button via history hook → Task 1 (hook) + Task 2 (wiring).
- Link-builders always-link, top-level (ArtistTile, LabelTile, ArtistCard, LabelCard, ArtistsTable, LabelsTable, ArtistsPanel, admin BacklogTable) → Tasks 3, 4, 5, 6.
- Callers simplify (Bucket/Curate/Category panels; PlaylistPlayerPanel gains links) → Tasks 3, 4.
- i18n `library.detail.back` → Task 1.
- Tests inverted/updated (PlaylistPlayerPanel, ArtistTile, LabelTile, ArtistsPanel, tables, LabelCard, ArtistDetailPage) → Tasks 2–6.
- Verification (typecheck + lint + test + browser) → Task 7.
- Non-goals (no backend/API/DB; library lists stay style-scoped; no collaborator links) → respected; only the `library` list routes keep `:styleId`.

**Placeholder scan:** No TBD/TODO; every code step shows exact content.

**Type consistency:** `styleId` is removed from the Props of `ArtistTile`, `LabelTile`, `ArtistsPanel`, `ArtistsTable`, `LabelsTable`, `ArtistCard`, `LabelCard`, `ArtistDetailHeader`, `LabelDetailHeader`; every call site that passed it is updated in the same task (3, 4, 5, 6, 2 respectively), keeping `pnpm typecheck` green at each commit. The hook name `useBackOrFallback` is consistent across Tasks 1 and 2.
