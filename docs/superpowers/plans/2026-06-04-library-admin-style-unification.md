# Library + Admin Style Unification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Library, Artist/Label detail, and Admin pages feel like one application by applying the existing design system consistently — unified page shell, one header pattern per layout, standard empty/loading/error states, and tokens instead of hardcoded values.

**Architecture:** No new design system; the project already has a strong one (`frontend/src/theme.ts` + `frontend/src/tokens.css`). The work is uptake: a new shared `PageHeader` for list/admin pages, dedup of the AI badge onto the existing `AiContentBadge`, an inline variant of the existing `EmptyState`, a `Container` in `AdminLayout` so every admin page gets the same width, and a sweep that replaces hardcoded `minWidth`/`w={320}`/`whiteSpace`/`'white'/'black'` with tokens.

**Tech Stack:** React 19, Mantine 9, react-router, react-i18next (single `en.json`), Vitest (jsdom) + `@vitest/browser` (Playwright) for layout/CSS, MSW for HTTP stubs, TanStack Query.

---

## Scope corrections discovered during grounding

The brainstorming spec made two assumptions that the codebase contradicts. This plan adjusts:

1. **`ArtistCard` / `LabelCard` are dead code** — imported only by their own tests (`grep` of `src` confirms no runtime consumer). The spec's "merge Tile + Card into one `EntityTile`" is moot. **Action:** delete the dead Cards and their tests instead of merging.
2. **`ArtistTile` / `LabelTile` live in player panels** (`playlists`, `triage`, `curate`, `categories`), not on the audited pages, and fetch from different hooks (`useArtistInfo` vs `useLabelInfo`). A full generic merge is a cross-feature refactor with playback re-render risk and an existing geometry browser test. **Action (in scope):** dedup the AI badge (`LabelTile` → `AiContentBadge`) and replace fixed `w={320}` with responsive `maw={320}`. **Out of scope:** merging the two tiles into one generic component.
3. **Detail headers are NOT routed through `PageHeader`.** `ArtistDetailHeader` is already the clean template (back-link → H2 → `AiContentBadge` → preference buttons → metadata). Unifying detail = make `LabelDetailHeader` match it (use `AiContentBadge`). `PageHeader` serves **list + admin** layouts, where the real divergence lives (width, `order={3}`, missing states). The detail "entity header" and the "page header" are two deliberate patterns for two different layouts. The curation UX of preference buttons next to the name is preserved.

## File structure

**New files:**
- `frontend/src/components/PageHeader.tsx` — shared header for list/admin pages (title `order={2}`, optional back-link, badges, right-aligned actions, subtitle, bottom slot). i18n-free; caller passes strings.
- `frontend/src/components/__tests__/PageHeader.test.tsx` — jsdom unit tests.
- `frontend/src/components/__tests__/PageHeader.browser.test.tsx` — Playwright layout test (actions right-aligned, subtitle below title).

**Modified files:**
- `frontend/src/tokens.css` — add a `.prewrap` utility class.
- `frontend/src/components/EmptyState.tsx` — add `variant?: 'page' | 'inline'`.
- `frontend/src/features/library/lib/aiContent.tsx` — extract tooltip styles to a token-based constant (kills `'white'/'black'`; fixes dark mode).
- `frontend/src/features/library/components/LabelDetailHeader.tsx` — use `AiContentBadge`; drop local tooltip/`AI_COLOR`/`formatAiContent`.
- `frontend/src/features/library/components/LabelTile.tsx` — use `AiContentBadge`; `w={320}`→`maw={320}`; `whiteSpace`→`prewrap`.
- `frontend/src/features/library/components/ArtistTile.tsx` — `w={320}`→`maw={320}`; `whiteSpace`→`prewrap`.
- `frontend/src/features/library/components/ArtistOverviewTab.tsx`, `LabelOverviewTab.tsx` — `whiteSpace`→`prewrap`.
- `frontend/src/features/library/components/LibraryFilters.tsx` — `style={{ minWidth }}`→`maw`.
- `frontend/src/features/library/routes/LibraryListPage.tsx`, `ArtistsListPage.tsx` — use `PageHeader`; empty table → `EmptyState variant="inline"`.
- `frontend/src/features/library/routes/ArtistDetailPage.tsx`, `LabelDetailPage.tsx` — 404 branch → `EmptyState variant="page"`.
- `frontend/src/features/admin/routes/AdminLayout.tsx` — wrap in `Container size="xl"`.
- `frontend/src/features/admin/routes/Admin*Page.tsx` (9 pages) — `PageHeader` (`order={2}` + subtitle), standard states.
- `frontend/src/i18n/en.json` — add admin subtitle keys + `run_detail.not_found`.

**Deleted files:**
- `frontend/src/features/library/components/ArtistCard.tsx` + `__tests__/ArtistCard.test.tsx`
- `frontend/src/features/library/components/LabelCard.tsx` + `__tests__/LabelCard.test.tsx`

## Commands (run from `frontend/`)

- Unit tests (jsdom): `pnpm test` (alias for `NODE_OPTIONS=--no-experimental-webstorage vitest run`)
- One file: `pnpm test src/components/__tests__/PageHeader.test.tsx`
- Browser tests (Playwright): `pnpm test:browser`
- Typecheck: `pnpm typecheck` (`tsc -b --noEmit`)
- Lint: `pnpm lint` (`eslint src`)

> **Worktree note (CLAUDE.md gotcha #3):** `pnpm` runs from `frontend/`. If `pnpm` is unavailable, the repo `.venv`/node tooling lives at the MAIN repo root, not the worktree.

> **Browser-test rule (CLAUDE.md gotcha #11):** jsdom applies no stylesheets — visual/layout assertions MUST go in `*.browser.test.tsx` and run via `pnpm test:browser` locally (CI has no browser).

---

## Phase 0 — Foundation primitives

### Task 1: `.prewrap` utility class + replace inline `whiteSpace`

**Files:**
- Modify: `frontend/src/tokens.css` (append a utilities block at end of file)
- Modify: `frontend/src/features/library/components/ArtistTile.tsx:100`
- Modify: `frontend/src/features/library/components/LabelTile.tsx:125`
- Modify: `frontend/src/features/library/components/ArtistOverviewTab.tsx` (line with `whiteSpace: 'pre-wrap'`)
- Modify: `frontend/src/features/library/components/LabelOverviewTab.tsx` (line with `whiteSpace: 'pre-wrap'`)

- [ ] **Step 1: Add the utility class to `tokens.css`**

Append at the end of `frontend/src/tokens.css`:

```css
/* ── Utilities ─────────────────────────────────────────── */
/* Preserve newlines in AI-generated prose (summaries, bios).
   Replaces 4× inline style={{ whiteSpace: 'pre-wrap' }}. */
.prewrap {
  white-space: pre-wrap;
}
```

- [ ] **Step 2: Replace the inline style in all four files**

In each file, change the `<Text ... style={{ whiteSpace: 'pre-wrap' }}>` to use the class. Example for `ArtistTile.tsx:99-101`:

```tsx
{showFullCard && info?.summary && (
  <Text size="sm" className="prewrap">
    {info.summary}
  </Text>
)}
```

Apply the identical change (`style={{ whiteSpace: 'pre-wrap' }}` → `className="prewrap"`) in `LabelTile.tsx`, `ArtistOverviewTab.tsx`, and `LabelOverviewTab.tsx`. If a `<Text>` already has a `className`, append `prewrap` to it.

- [ ] **Step 3: Run typecheck + existing tests**

Run: `pnpm typecheck && pnpm test src/features/library/components/__tests__/ArtistTile.test.tsx src/features/library/components/__tests__/LabelTile.test.tsx`
Expected: PASS (no behavior change; class swap only).

- [ ] **Step 4: Grep to confirm no inline `pre-wrap` remains**

Run: `grep -rn "whiteSpace: 'pre-wrap'" src` (from `frontend/`)
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add src/tokens.css src/features/library/components/ArtistTile.tsx src/features/library/components/LabelTile.tsx src/features/library/components/ArtistOverviewTab.tsx src/features/library/components/LabelOverviewTab.tsx
git commit -m "refactor(library): replace inline pre-wrap with .prewrap utility"
```

---

### Task 2: `EmptyState` inline variant

**Files:**
- Modify: `frontend/src/components/EmptyState.tsx`
- Test: `frontend/src/components/__tests__/EmptyState.test.tsx` (create if absent)

- [ ] **Step 1: Write the failing test**

Create/append `frontend/src/components/__tests__/EmptyState.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { EmptyState } from '../EmptyState';

function renderEmpty(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('EmptyState', () => {
  it('renders title and body', () => {
    renderEmpty(<EmptyState title="Nothing here" body="Try again later" />);
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
    expect(screen.getByText('Try again later')).toBeInTheDocument();
  });

  it('inline variant uses an h3 heading (not the page-level h2)', () => {
    renderEmpty(<EmptyState title="Empty list" variant="inline" />);
    const heading = screen.getByText('Empty list');
    expect(heading.tagName).toBe('H3');
  });

  it('page variant keeps the h2 heading', () => {
    renderEmpty(<EmptyState title="Not found" variant="page" />);
    expect(screen.getByText('Not found').tagName).toBe('H2');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test src/components/__tests__/EmptyState.test.tsx`
Expected: FAIL — `variant` prop not yet supported; inline title renders as `H2`.

- [ ] **Step 3: Implement the variant**

Replace `frontend/src/components/EmptyState.tsx` with:

```tsx
import { Button, Center, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export interface EmptyStateProps {
  title: string;
  body?: ReactNode;
  icon?: ReactNode;
  action?: { label: string; onClick: () => void };
  /** 'page' = full-height (404 / route-level). 'inline' = compact, fits inside a table/section. */
  variant?: 'page' | 'inline';
}

export function EmptyState({ title, body, icon, action, variant = 'page' }: EmptyStateProps) {
  const isInline = variant === 'inline';
  return (
    <Center mih={isInline ? undefined : '60vh'} py={isInline ? 'xl' : undefined} p={isInline ? undefined : 'xl'}>
      <Stack align="center" gap="md" maw={420}>
        {icon}
        <Title order={isInline ? 3 : 2} ta="center">
          {title}
        </Title>
        {body &&
          (typeof body === 'string' ? (
            <Text c="dimmed" ta="center">
              {body}
            </Text>
          ) : (
            body
          ))}
        {action && (
          <Button onClick={action.onClick} variant="default">
            {action.label}
          </Button>
        )}
      </Stack>
    </Center>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test src/components/__tests__/EmptyState.test.tsx`
Expected: PASS.

- [ ] **Step 5: Confirm existing 404 callers still compile (default variant unchanged)**

Run: `pnpm typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/EmptyState.tsx src/components/__tests__/EmptyState.test.tsx
git commit -m "feat(components): add inline variant to EmptyState"
```

---

### Task 3: Token-based AI tooltip styles in `AiContentBadge`

**Files:**
- Modify: `frontend/src/features/library/lib/aiContent.tsx`

- [ ] **Step 1: Replace hardcoded colors with semantic tokens**

In `frontend/src/features/library/lib/aiContent.tsx`, add a shared style constant and use it in both the `Tooltip` and the `outline` badge. Replace the literal `'white'`/`'black'` values:

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

/** Tooltip surface for AI reasoning — token-based so dark mode + accent flow through. */
const aiTooltipStyles = {
  tooltip: {
    backgroundColor: 'var(--color-bg-elevated)',
    color: 'var(--color-fg)',
    padding: '12px 16px',
    lineHeight: 1.5,
    border: '1px solid var(--color-border)',
    boxShadow: 'var(--mantine-shadow-md)',
  },
} as const;

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
      <Badge variant="outline" style={{ cursor: 'help' }}>
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
      styles={aiTooltipStyles}
    >
      {badge}
    </Tooltip>
  );
}
```

> Note: the `outline` badge dropped the `backgroundColor:'white', color:'black', borderColor:'black'` overrides — Mantine's `variant="outline"` already reads themed fg/border, which is the point (these were the hardcodes the audit flagged).

- [ ] **Step 2: Run existing badge consumers' tests**

Run: `pnpm test src/features/library/components/__tests__/ArtistTile.test.tsx`
Expected: PASS (ArtistTile already uses `AiContentBadge variant="outline"`).

- [ ] **Step 3: Typecheck**

Run: `pnpm typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/features/library/lib/aiContent.tsx
git commit -m "refactor(library): token-based AI tooltip styles, fix dark mode"
```

---

## Phase 1 — Kill duplication and dead code

### Task 4: Delete dead `ArtistCard` / `LabelCard`

**Files:**
- Delete: `frontend/src/features/library/components/ArtistCard.tsx`
- Delete: `frontend/src/features/library/components/LabelCard.tsx`
- Delete: `frontend/src/features/library/components/__tests__/ArtistCard.test.tsx`
- Delete: `frontend/src/features/library/components/__tests__/LabelCard.test.tsx`

- [ ] **Step 1: Confirm no runtime consumer**

Run: `grep -rn "ArtistCard\|LabelCard" src --include=*.tsx | grep -v "__tests__" | grep -v "ArtistCard.tsx\|LabelCard.tsx"`
Expected: no matches (only the definitions and tests reference them).

- [ ] **Step 2: Delete the four files**

```bash
git rm src/features/library/components/ArtistCard.tsx src/features/library/components/LabelCard.tsx src/features/library/components/__tests__/ArtistCard.test.tsx src/features/library/components/__tests__/LabelCard.test.tsx
```

- [ ] **Step 3: Typecheck + full unit run**

Run: `pnpm typecheck && pnpm test`
Expected: PASS (nothing imported them).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(library): delete unused ArtistCard and LabelCard"
```

---

### Task 5: `LabelDetailHeader` uses `AiContentBadge`

**Files:**
- Modify: `frontend/src/features/library/components/LabelDetailHeader.tsx`

- [ ] **Step 1: Replace the inline tooltip/badge with `AiContentBadge`**

Rewrite `frontend/src/features/library/components/LabelDetailHeader.tsx` to mirror `ArtistDetailHeader` (delete local `AI_COLOR`, `formatAiContent`, the `aiBadge` block, and the `Badge`/`Tooltip` imports):

```tsx
import { Group, Title, Text, Anchor, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useBackOrFallback } from '../hooks/useBackOrFallback';
import type { LabelDetail } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';
import { AiContentBadge } from '../lib/aiContent';
import { LabelPreferenceButtons } from './LabelPreferenceButtons';
import { useAuth } from '../../../auth/useAuth';
import { useEnrichLabelAuto } from '../hooks/useEnrichLabelAuto';

interface Props {
  info: LabelDetail;
  labelId: string;
}

export function LabelDetailHeader({ info, labelId }: Props) {
  const { t } = useTranslation();
  const goBack = useBackOrFallback('/library');
  const { state } = useAuth();
  const isAdmin = state.status === 'authenticated' && state.user.is_admin;
  const enrich = useEnrichLabelAuto();
  const rec = info as Record<string, unknown>;
  const labelName = typeof rec.label_name === 'string' ? rec.label_name : '';
  const country = typeof rec.country === 'string' ? rec.country : '';
  const foundedYear = typeof rec.founded_year === 'number' ? rec.founded_year : null;
  const aiContent = typeof rec.ai_content === 'string' ? rec.ai_content : '';
  const aiReasoning = typeof rec.ai_reasoning === 'string' ? rec.ai_reasoning : '';
  const myPreference =
    rec.my_preference === 'liked' || rec.my_preference === 'disliked' ? rec.my_preference : null;

  return (
    <>
      <Anchor component="button" type="button" onClick={goBack} size="sm">
        {t('library.detail.back')}
      </Anchor>
      <Group gap="sm" mt="xs" align="center" wrap="wrap">
        <Title order={2}>{labelName}</Title>
        <AiContentBadge content={aiContent} reasoning={aiReasoning} variant="colored" />
        <LabelPreferenceButtons labelId={labelId} current={myPreference} size="md" />
        {isAdmin && (
          <Button
            size="xs"
            variant="light"
            loading={enrich.isPending}
            onClick={() => enrich.mutate({ labelId })}
          >
            {t('library.detail.admin_search_now')}
          </Button>
        )}
      </Group>
      <Group gap="xs" mt="xs">
        {country && (
          <Text>
            {countryFlag(country)} {country}
          </Text>
        )}
        {foundedYear !== null && (
          <Text c="dimmed">· {t('library.detail.founded', { year: foundedYear })}</Text>
        )}
      </Group>
    </>
  );
}
```

> Behavior change: the label AI badge now renders the `colored` variant (matching Artist), not the old white outline. This is the intended unification.

- [ ] **Step 2: Run the label detail tests**

Run: `pnpm test src/features/library/routes/__tests__ src/features/library/hooks/__tests__/useLabelDetail.test.tsx`
Expected: PASS. If a test asserts the old white-outline badge text/markup, update it to expect the `colored` badge (text is still `AI <VALUE>`).

- [ ] **Step 3: Typecheck**

Run: `pnpm typecheck`
Expected: PASS — no unused imports remain.

- [ ] **Step 4: Commit**

```bash
git add src/features/library/components/LabelDetailHeader.tsx
git commit -m "refactor(library): LabelDetailHeader uses shared AiContentBadge"
```

---

### Task 6: `LabelTile` uses `AiContentBadge`

**Files:**
- Modify: `frontend/src/features/library/components/LabelTile.tsx`

- [ ] **Step 1: Replace the inline tooltip block (lines 72-102) with `AiContentBadge`**

Add the import and replace the conditional `Tooltip`/`Badge` block. New import line (top of file):

```tsx
import { AiContentBadge } from '../lib/aiContent';
```

Remove `Badge` and `Tooltip` from the `@mantine/core` import. Replace the block currently rendering the inline tooltip:

```tsx
        {showFullCard && (
          <AiContentBadge content={aiContent} reasoning={aiReasoning} variant="outline" />
        )}
```

(`AiContentBadge` already returns `null` when `content` is empty, so the inner `aiContent &&` guard is no longer needed; keep the `showFullCard &&` wrapper to preserve minimal-mode behavior.)

- [ ] **Step 2: Run LabelTile tests**

Run: `pnpm test src/features/library/components/__tests__/LabelTile.test.tsx`
Expected: PASS. The badge still renders `AI <VALUE>` text; update any assertion that targeted the old inline markup.

- [ ] **Step 3: Typecheck**

Run: `pnpm typecheck`
Expected: PASS (no unused `Badge`/`Tooltip`).

- [ ] **Step 4: Commit**

```bash
git add src/features/library/components/LabelTile.tsx
git commit -m "refactor(library): LabelTile uses shared AiContentBadge"
```

---

### Task 7: Tiles use responsive `maw` instead of fixed `w={320}`

**Files:**
- Modify: `frontend/src/features/library/components/ArtistTile.tsx:72`
- Modify: `frontend/src/features/library/components/LabelTile.tsx:67`
- Test: `frontend/src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx` (existing geometry test — must still pass)

- [ ] **Step 1: Change the outer `Stack` width**

In both tiles, change `<Stack gap="sm" w={320}>` to `<Stack gap="sm" maw={320}>`. `maw` (max-width) keeps the current visual cap but lets the tile shrink inside narrow player panels instead of overflowing.

- [ ] **Step 2: Run the existing browser geometry test**

Run: `pnpm test:browser src/features/library/components/__tests__/ArtistsPanel.browser.test.tsx`
Expected: PASS — the panel layout (main tile + chip row, chips within 8px y) is unchanged at the panel's natural width.

- [ ] **Step 3: Run jsdom tile tests + typecheck**

Run: `pnpm test src/features/library/components/__tests__/ArtistTile.test.tsx src/features/library/components/__tests__/LabelTile.test.tsx && pnpm typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/features/library/components/ArtistTile.tsx src/features/library/components/LabelTile.tsx
git commit -m "refactor(library): tiles use responsive maw, drop fixed w=320"
```

---

## Phase 2 — PageHeader + Library lists

### Task 8: Create `PageHeader`

**Files:**
- Create: `frontend/src/components/PageHeader.tsx`
- Test: `frontend/src/components/__tests__/PageHeader.test.tsx`
- Test: `frontend/src/components/__tests__/PageHeader.browser.test.tsx`

- [ ] **Step 1: Write the failing unit test**

Create `frontend/src/components/__tests__/PageHeader.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { PageHeader } from '../PageHeader';

function renderHeader(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('PageHeader', () => {
  it('renders the title as an h2', () => {
    renderHeader(<PageHeader title="Enrichment Runs" />);
    const heading = screen.getByText('Enrichment Runs');
    expect(heading.tagName).toBe('H2');
  });

  it('renders a subtitle when provided', () => {
    renderHeader(<PageHeader title="Runs" subtitle="Queue and history of runs" />);
    expect(screen.getByText('Queue and history of runs')).toBeInTheDocument();
  });

  it('renders a back-link that fires onBack', async () => {
    const onBack = vi.fn();
    renderHeader(<PageHeader title="Artist" backLink={{ label: '← Library', onClick: onBack }} />);
    screen.getByRole('button', { name: '← Library' }).click();
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('renders actions and bottom children', () => {
    renderHeader(
      <PageHeader title="Labels" actions={<button>Add</button>}>
        <div data-testid="tabs">tabs</div>
      </PageHeader>,
    );
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument();
    expect(screen.getByTestId('tabs')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm test src/components/__tests__/PageHeader.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `PageHeader`**

Create `frontend/src/components/PageHeader.tsx`:

```tsx
import { Anchor, Group, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export interface PageHeaderProps {
  /** Page title — always rendered as an h2 (order={2}). */
  title: ReactNode;
  /** Inline back-link, detail pages only. */
  backLink?: { label: string; onClick: () => void };
  /** Inline nodes next to the title (badges, status). */
  badges?: ReactNode;
  /** Right-aligned slot (primary actions). */
  actions?: ReactNode;
  /** Muted line under the title (description / metadata). String or node. */
  subtitle?: ReactNode;
  /** Bottom slot: Tabs / Filters / Toolbar. */
  children?: ReactNode;
}

export function PageHeader({ title, backLink, badges, actions, subtitle, children }: PageHeaderProps) {
  return (
    <Stack gap="xs">
      {backLink && (
        <Anchor component="button" type="button" onClick={backLink.onClick} size="sm">
          {backLink.label}
        </Anchor>
      )}
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Group gap="sm" align="center" wrap="wrap">
          <Title order={2}>{title}</Title>
          {badges}
        </Group>
        {actions && <Group gap="xs">{actions}</Group>}
      </Group>
      {subtitle &&
        (typeof subtitle === 'string' ? (
          <Text c="dimmed" size="sm">
            {subtitle}
          </Text>
        ) : (
          subtitle
        ))}
      {children}
    </Stack>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pnpm test src/components/__tests__/PageHeader.test.tsx`
Expected: PASS.

- [ ] **Step 5: Write the browser layout test**

Create `frontend/src/components/__tests__/PageHeader.browser.test.tsx`:

```tsx
import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { PageHeader } from '../PageHeader';

function renderHeader() {
  return render(
    <MantineProvider>
      <div style={{ width: 800 }}>
        <PageHeader
          title="Labels"
          actions={<button>Add</button>}
          subtitle="All labels in this style"
        />
      </div>
    </MantineProvider>,
  );
}

describe('PageHeader layout', () => {
  test('actions sit to the right of the title', () => {
    renderHeader();
    const title = screen.getByText('Labels').getBoundingClientRect();
    const action = screen.getByRole('button', { name: 'Add' }).getBoundingClientRect();
    expect(action.left).toBeGreaterThan(title.right);
  });

  test('subtitle sits below the title row', () => {
    renderHeader();
    const title = screen.getByText('Labels').getBoundingClientRect();
    const subtitle = screen.getByText('All labels in this style').getBoundingClientRect();
    expect(subtitle.top).toBeGreaterThan(title.bottom - 1);
  });
});
```

- [ ] **Step 6: Run the browser test**

Run: `pnpm test:browser src/components/__tests__/PageHeader.browser.test.tsx`
Expected: PASS.

- [ ] **Step 7: Lint + typecheck**

Run: `pnpm typecheck && pnpm lint`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/components/PageHeader.tsx src/components/__tests__/PageHeader.test.tsx src/components/__tests__/PageHeader.browser.test.tsx
git commit -m "feat(components): add shared PageHeader"
```

---

### Task 9: Library list pages adopt `PageHeader`; filters use `maw`; empty state

**Files:**
- Modify: `frontend/src/features/library/components/LibraryFilters.tsx:57,64,74`
- Modify: `frontend/src/features/library/routes/LibraryListPage.tsx`
- Modify: `frontend/src/features/library/routes/ArtistsListPage.tsx`

- [ ] **Step 1: `LibraryFilters` — `minWidth` → `maw`**

In `frontend/src/features/library/components/LibraryFilters.tsx`, replace the three inline styles:
- Line 57: `style={{ minWidth: 200 }}` → `miw={200}`
- Line 64: `style={{ minWidth: 240, flex: 1 }}` → `miw={240} style={{ flex: 1 }}`
- Line 74: `style={{ minWidth: 180 }}` → `miw={180}`

(`miw` is Mantine's min-width style prop — token-aware and lint-clean. The search input keeps `flex: 1` since there is no Mantine prop for `flex`.)

- [ ] **Step 2: `LibraryListPage` — wrap header in `PageHeader`**

In `frontend/src/features/library/routes/LibraryListPage.tsx`, replace the `Title` + `EntityTabs` with a `PageHeader` (tabs go in the bottom slot), and render an inline empty state when the list is empty. Update the imports and the returned JSX:

```tsx
import { Container, Stack } from '@mantine/core';
// ...existing imports...
import { PageHeader } from '../../../components/PageHeader';
import { EmptyState } from '../../../components/EmptyState';
```

```tsx
  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <PageHeader title={t('library.list.title')}>
          <EntityTabs active="labels" styleId={styleId} />
        </PageHeader>
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
        {!query.isLoading && items.length === 0 ? (
          <EmptyState variant="inline" title={t('library.list.empty')} />
        ) : (
          <LabelsTable
            items={items}
            isLoading={query.isLoading}
            page={page}
            pageCount={pageCount}
            onPageChange={onPageChange}
          />
        )}
      </Stack>
    </Container>
  );
```

- [ ] **Step 3: `ArtistsListPage` — same treatment**

Apply the identical change to `frontend/src/features/library/routes/ArtistsListPage.tsx`: import `PageHeader` and `EmptyState`, wrap the title with `<PageHeader title={...}><EntityTabs active="artists" styleId={styleId} /></PageHeader>`, and gate the `ArtistsTable` behind the same `items.length === 0` inline empty state using key `library.list.empty`.

- [ ] **Step 4: Add the `library.list.empty` i18n key**

In `frontend/src/i18n/en.json`, inside the existing `library.list` object, add:

```json
"empty": "Nothing here yet for this style."
```

- [ ] **Step 5: Run the list page tests + typecheck + lint**

Run: `pnpm test src/features/library/routes/__tests__/ArtistsListPage.test.tsx && pnpm typecheck && pnpm lint`
Expected: PASS. If a test queried the bare `Title`, it still finds the text via `PageHeader`'s h2.

- [ ] **Step 6: Commit**

```bash
git add src/features/library/components/LibraryFilters.tsx src/features/library/routes/LibraryListPage.tsx src/features/library/routes/ArtistsListPage.tsx src/i18n/en.json
git commit -m "feat(library): list pages use PageHeader, tokenized filter widths, empty state"
```

---

## Phase 3 — Admin

### Task 10: `AdminLayout` gets a `Container`

**Files:**
- Modify: `frontend/src/features/admin/routes/AdminLayout.tsx`

- [ ] **Step 1: Wrap the layout in `Container size="xl"`**

In `frontend/src/features/admin/routes/AdminLayout.tsx`, add `Container` to the import and wrap the existing `Stack`:

```tsx
import { Container, Stack, Tabs } from '@mantine/core';
```

```tsx
  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Tabs value={active} onChange={(v) => v && navigate(v)} keepMounted={false}>
          <Tabs.List>
            {TABS.map((tab) => (
              <Tabs.Tab key={tab.value} value={tab.value}>
                {tab.label}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
        <Outlet />
        <RunProgressToast />
      </Stack>
    </Container>
  );
```

This gives every admin page the same `xl` width as Library lists in one edit. Individual admin pages must NOT add their own `Container` (would double-pad).

- [ ] **Step 2: Typecheck + admin layout test (if present)**

Run: `pnpm typecheck && pnpm test src/features/admin`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/features/admin/routes/AdminLayout.tsx
git commit -m "feat(admin): wrap admin pages in xl Container"
```

---

### Task 11: Admin i18n keys (subtitles + run-not-found)

**Files:**
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add subtitle + error keys**

Add the following keys to `frontend/src/i18n/en.json` in their existing namespaces:

Under `admin.coverage`:
```json
"subtitle": "Track coverage by week across styles."
```
Under `admin.spotify_not_found`:
```json
"subtitle": "Tracks still waiting for a Spotify match."
```
Under `admin_enrichment.backlog`:
```json
"subtitle": "Labels and artists missing enrichment info."
```
Under `admin_enrichment.runs`:
```json
"subtitle": "Queue and history of enrichment runs."
```
Under `admin_enrichment.run_detail`:
```json
"not_found": "Run not found."
```
Under `admin_auto_enrich`:
```json
"subtitle": "Configure automatic enrichment per entity type."
```

> Reuse: artist backlog/runs pages share `admin_enrichment.backlog.*` / `admin_enrichment.runs.*` keys (confirmed in `AdminLayout`/grounding), so the same subtitle covers both label and artist variants.

- [ ] **Step 2: Validate JSON**

Run: `node -e "require('./src/i18n/en.json')"` (from `frontend/`)
Expected: no error (valid JSON).

- [ ] **Step 3: Commit**

```bash
git add src/i18n/en.json
git commit -m "feat(i18n): admin page subtitles and run-not-found copy"
```

---

### Task 12: Admin pages adopt `PageHeader` + standard states

Each page: replace `<Title order={3}>{...}</Title>` (or `order={2}` ad-hoc) with `<PageHeader title={...} subtitle={t(...)}>{existing controls}</PageHeader>`, and wire standard states. The page's outer wrapper stays `<Stack gap="md">` (Container comes from `AdminLayout`). Import `PageHeader` from `'../../../components/PageHeader'` and `EmptyState` from `'../../../components/EmptyState'` where used.

Apply per-file as follows (exact title key, subtitle key, and state wiring):

| File | Title key (was) | Subtitle key (new) | State wiring |
|---|---|---|---|
| `AdminCoveragePage.tsx` | `admin.coverage.title` (order 2) | `admin.coverage.subtitle` | YearNavigator stays in bottom slot; keep existing `Alert` for `load_failed` |
| `AdminSpotifyNotFoundPage.tsx` | `admin.spotify_not_found.title` (order 2) | `admin.spotify_not_found.subtitle` | states stay inside `SpotifyNotFoundTable` |
| `AdminEnrichmentBacklogPage.tsx` | `admin_enrichment.backlog.title` (order 3) | `admin_enrichment.backlog.subtitle` | BacklogToolbar in bottom slot; swap empty `Center+Text` → `EmptyState variant="inline" title={t('admin_enrichment.backlog.empty')}` |
| `AdminEnrichmentRunsPage.tsx` | `admin_enrichment.runs.title` (order 3) | `admin_enrichment.runs.subtitle` | filter `Group` in bottom slot; add empty + error (below) |
| `AdminEnrichmentRunDetailPage.tsx` | (none — RunDetailHeader) | — | replace hardcoded `<Text c="red">Run not found</Text>` with `<EmptyState variant="page" title={t('admin_enrichment.run_detail.not_found')} />` |
| `AdminArtistEnrichmentBacklogPage.tsx` | `admin_enrichment.backlog.title` (order 3) | `admin_enrichment.backlog.subtitle` | same as label backlog |
| `AdminArtistEnrichmentRunsPage.tsx` | `admin_enrichment.runs.title` (order 3) | `admin_enrichment.runs.subtitle` | same as label runs |
| `AdminArtistEnrichmentRunDetailPage.tsx` | (none) | — | same as label run detail |
| `AdminAutoEnrichPage.tsx` | `admin_auto_enrich.title` (order 3) | `admin_auto_enrich.subtitle` | tabs stay in bottom slot; per-tab Skeleton/Alert already present |

- [ ] **Step 1: Exemplar — `AdminEnrichmentRunsPage.tsx` (full rewrite)**

This page is the exemplar for the runs pattern (header + empty + error). Replace `frontend/src/features/admin/routes/AdminEnrichmentRunsPage.tsx`:

```tsx
import { Stack, Select, Center, Group, SegmentedControl, Text, Alert, Button, Skeleton } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useEnrichmentRuns } from '../hooks/useEnrichmentRuns';
import { RunsTable } from '../components/enrichment/RunsTable';
import { PageHeader } from '../../../components/PageHeader';
import { EmptyState } from '../../../components/EmptyState';

export function AdminEnrichmentRunsPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<'all' | 'queued' | 'running' | 'completed' | 'failed'>('all');
  const [source, setSource] = useState<'all' | 'manual' | 'auto'>('all');
  const query = useEnrichmentRuns({
    status,
    source: source === 'all' ? undefined : source,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Stack gap="md">
      <PageHeader title={t('admin_enrichment.runs.title')} subtitle={t('admin_enrichment.runs.subtitle')}>
        <Group align="flex-end">
          <Select
            label={t('admin_enrichment.runs.filter_status')}
            value={status}
            onChange={(v) => v && setStatus(v as typeof status)}
            data={[
              { value: 'all', label: 'all' },
              { value: 'queued', label: t('admin_enrichment.status.queued') },
              { value: 'running', label: t('admin_enrichment.status.running') },
              { value: 'completed', label: t('admin_enrichment.status.completed') },
              { value: 'failed', label: t('admin_enrichment.status.failed') },
            ]}
            maw={240}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>{t('admin_enrichment.runs.filter_source')}</Text>
            <SegmentedControl
              value={source}
              onChange={(v) => setSource(v as typeof source)}
              data={[
                { value: 'all', label: t('admin_enrichment.runs.source_all') },
                { value: 'manual', label: t('admin_enrichment.runs.source_manual') },
                { value: 'auto', label: t('admin_enrichment.runs.source_auto') },
              ]}
            />
          </Stack>
        </Group>
      </PageHeader>

      {query.isError ? (
        <Alert color="red">{t('admin.coverage.load_failed')}</Alert>
      ) : query.isLoading ? (
        <Skeleton height={320} radius="md" />
      ) : items.length === 0 ? (
        <EmptyState variant="inline" title={t('admin_enrichment.runs.empty')} />
      ) : (
        <RunsTable items={items} />
      )}

      {query.hasNextPage && (
        <Center mt="md">
          <Button variant="default" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            {t('admin_enrichment.backlog.load_more')}
          </Button>
        </Center>
      )}
    </Stack>
  );
}
```

> Note: the literal `Load more` is replaced with the existing `admin_enrichment.backlog.load_more` key (tokenized copy), and a generic load-failed `Alert` reuses `admin.coverage.load_failed`.

- [ ] **Step 2: Exemplar — `AdminEnrichmentBacklogPage.tsx` (header + empty swap)**

In `frontend/src/features/admin/routes/AdminEnrichmentBacklogPage.tsx`: add the `PageHeader`/`EmptyState` imports; replace `<Title order={3}>{t('admin_enrichment.backlog.title')}</Title>` + the `BacklogToolbar` with:

```tsx
      <PageHeader
        title={t('admin_enrichment.backlog.title')}
        subtitle={t('admin_enrichment.backlog.subtitle')}
      >
        <BacklogToolbar
          style={style}
          onStyleChange={setStyle}
          status={status}
          onStatusChange={setStatus}
          selectedCount={selected.size}
          onEnqueueClick={() => setDrawerOpen(true)}
          styleOptions={styleOptions}
          stylesLoading={stylesQuery.isLoading}
        />
      </PageHeader>
```

and replace the empty branch (lines 70-73) `<Center mt="lg"><Text c="dimmed">{t('admin_enrichment.backlog.empty')}</Text></Center>` with:

```tsx
        <EmptyState variant="inline" title={t('admin_enrichment.backlog.empty')} />
```

Drop now-unused `Title`, `Center`, `Text` from the `@mantine/core` import if no longer referenced.

- [ ] **Step 3: Apply the per-file table to the remaining 7 pages**

For each remaining file in the table above, make the same mechanical edit: import `PageHeader` (and `EmptyState` where the row's state wiring needs it), wrap the existing title + immediately-following controls in `<PageHeader title={t(<title key>)} subtitle={t(<subtitle key>)}>...controls...</PageHeader>`, and apply the row's state wiring. Specifics:
- `AdminCoveragePage.tsx`: title key `admin.coverage.title`, subtitle `admin.coverage.subtitle`, put `YearNavigator` in the bottom slot, keep the existing `Alert`.
- `AdminSpotifyNotFoundPage.tsx`: title `admin.spotify_not_found.title`, subtitle `admin.spotify_not_found.subtitle`, no extra state wiring.
- `AdminArtistEnrichmentBacklogPage.tsx`: identical to Step 2 but in the artist file.
- `AdminArtistEnrichmentRunsPage.tsx`: identical to Step 1's header + state pattern, in the artist file.
- `AdminEnrichmentRunDetailPage.tsx` and `AdminArtistEnrichmentRunDetailPage.tsx`: replace `<Text c="red">Run not found</Text>` with `<EmptyState variant="page" title={t('admin_enrichment.run_detail.not_found')} />`; import `EmptyState`, drop the hardcoded string.
- `AdminAutoEnrichPage.tsx`: title `admin_auto_enrich.title`, subtitle `admin_auto_enrich.subtitle`, tabs stay in the bottom slot (per-tab Skeleton/Alert already present — leave them).

- [ ] **Step 4: Run all admin tests + typecheck + lint**

Run: `pnpm test src/features/admin && pnpm typecheck && pnpm lint`
Expected: PASS. Update any admin test that queried a bare `Title order={3}` — the text is now an h2 inside `PageHeader`, still findable by text.

- [ ] **Step 5: Commit**

```bash
git add src/features/admin/routes
git commit -m "feat(admin): unify page headers (order 2 + subtitle) and states"
```

---

## Phase 4 — Detail 404 + verification

### Task 13: Artist/Label detail 404 uses `EmptyState`

**Files:**
- Modify: `frontend/src/features/library/routes/ArtistDetailPage.tsx:21-29`
- Modify: `frontend/src/features/library/routes/LabelDetailPage.tsx:21-29`

- [ ] **Step 1: Replace the ad-hoc 404 block**

In both pages, replace the 404 branch (`<Container py="md"><Stack gap="sm"><Title order={3}>...</Title><Text c="dimmed">...</Text></Stack></Container>`) with `EmptyState`. Update imports (`EmptyState` in, drop `Title`/`Stack`/`Text` if now unused — note `Title` is still used elsewhere in the file for the links card, keep it; `Container` stays for the main return). New 404 branch:

```tsx
    if (is404) {
      return (
        <EmptyState
          variant="page"
          title={t('library.detail.no_info_title')}
          body={t('library.detail.no_info_body')}
        />
      );
    }
```

Add import: `import { EmptyState } from '../../../components/EmptyState';`

- [ ] **Step 2: Run detail page tests + typecheck**

Run: `pnpm test src/features/library/routes/__tests__/ArtistDetailPage.test.tsx && pnpm typecheck`
Expected: PASS. If a test asserted the 404 heading was an h3, update it to find the text (now h2 via `EmptyState`).

- [ ] **Step 3: Commit**

```bash
git add src/features/library/routes/ArtistDetailPage.tsx src/features/library/routes/LabelDetailPage.tsx
git commit -m "refactor(library): detail 404 uses EmptyState"
```

---

### Task 14: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Confirm no hardcoded leftovers**

Run (from `frontend/`):
```bash
grep -rn "whiteSpace: 'pre-wrap'\|minWidth: 2\|w={320}\|backgroundColor: 'white'\|color: 'black'" src
```
Expected: no matches in `library`/`admin` source (the sweep is complete).

- [ ] **Step 2: Run the full unit suite**

Run: `pnpm test`
Expected: PASS (all green).

- [ ] **Step 3: Run the browser suite**

Run: `pnpm test:browser`
Expected: PASS (`PageHeader.browser`, `ArtistsPanel.browser`, and any other `*.browser.test.tsx`).

- [ ] **Step 4: Typecheck + lint (CI gates — CLAUDE.md memory: run locally)**

Run: `pnpm typecheck && pnpm lint`
Expected: both PASS.

- [ ] **Step 5: Manual visual check (real browser)**

`cd frontend && pnpm dev` (needs `frontend/.env.local` with `VITE_API_BASE_URL`). Spot-check: Library list, Artists list, an Artist detail, a Label detail, Admin Coverage, Admin Label Runs, Admin Run detail (force a 404). Confirm: same width rhythm, h2 titles, subtitles present on admin, empty/error states render. Capture before/after screenshots.

- [ ] **Step 6: Final commit (if any lint:fix/format applied)**

```bash
git add -A
git commit -m "chore(frontend): style unification verification pass"
```

---

## Self-review (author checklist — completed)

**Spec coverage:** All 7 contract rules map to tasks — width (Task 9 `Container xl`, Task 10 AdminLayout, detail already `lg`), PageHeader (Task 8/9/12), title hierarchy order=2 (Task 9/12/13), states (Task 2 EmptyState inline, Task 12 admin states, Task 13 detail 404), entity tile cleanup (Tasks 4/6/7 — adjusted: delete dead Cards + align tiles, not a merge — see Scope corrections), AI badge dedup (Tasks 3/5/6), token hygiene (Tasks 1/3/7/9). 

**Placeholder scan:** No "TBD"/"add error handling" placeholders; the admin per-file table enumerates exact keys and state wiring per file with two full exemplars.

**Type consistency:** `PageHeader` prop names (`title`, `backLink`, `badges`, `actions`, `subtitle`, `children`) and `EmptyState` `variant` are used identically across Tasks 8/9/12/13. `miw`/`maw` are real Mantine style props. i18n keys added in Tasks 9/11 are the exact keys referenced in Tasks 9/12/13.

**Known deviations from spec (intentional, flagged to user):** dead Card deletion replaces "Tile+Card merge"; detail headers keep their own pattern (not routed through `PageHeader`); generic `EntityTile` dropped.
