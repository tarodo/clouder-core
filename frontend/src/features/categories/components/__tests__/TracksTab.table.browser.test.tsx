/**
 * Browser-mode layout of the desktop category table beside the player (792px: a 1274px window, sidebar collapsed): every row is one
 * title-and-mix high whatever it holds (long names truncate, tags stay on one line); the default
 * columns fit, more scroll sideways in the table's own box. jsdom applies no stylesheets, so this
 * lives here (gotcha #11).
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';

vi.mock('../../../tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../tags')>();
  return {
    ...actual,
    TagsFilterBar: () => <div data-testid="tags-filter-bar" />,
    TagsManagerModal: () => null,
  };
});
vi.mock('../../hooks/useCategoriesByStyle', () => ({
  useCategoriesByStyle: () => ({ data: { items: [] }, isLoading: false }),
}));

import { TracksTab, type TracksTabProps } from '../TracksTab';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';

function mk(i: number, over: Partial<CategoryTrack>): CategoryTrack {
  return {
    id: `t${i}`,
    title: `Track ${i}`,
    mix_name: 'Original Mix',
    artists: [{ id: 'a1', name: 'Alkali.' }],
    label: { id: 'l1', name: 'Fokuz Recordings' },
    bpm: 87,
    length_ms: 222_000,
    publish_date: null,
    spotify_release_date: '2026-10-16',
    isrc: null,
    spotify_id: 'sp',
    release_type: null,
    used_in_playlist: false,
    added_at: '2026-10-29T12:00:00Z',
    source_triage_block_id: null,
    key_camelot: '4A',
    key_name: 'F Minor',
    comment_count: 12,
    tags: [],
    ...over,
  };
}

const items = [
  mk(0, {
    title: 'An Extremely Long Track Title That Never Seems To End Anywhere',
    mix_name: 'Extended Original Club Mix Remastered',
    artists: [
      { id: 'a1', name: 'Prepare The Others' },
      { id: 'a2', name: 'Vice Versa AU' },
      { id: 'a3', name: 'Wizmathics' },
    ],
    label: { id: 'l2', name: 'Abstract Logic Recordings International' },
    used_in_playlist: true,
    ai_verdict: 'high',
    comment_count: 100,
    tags: ['5', 'p5', 'RG', 'VM', 'JZ', 'U'].map((name, i) => ({ id: `g${i}`, name, color: null })),
  }),
  mk(1, { mix_name: null, tags: [] }),
  mk(2, { tags: [{ id: 'g0', name: '5', color: null }] }),
];

function props(rows: CategoryTrack[]): TracksTabProps {
  return {
    categoryId: 'c1',
    styleId: 's1',
    items: rows,
    total: rows.length,
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    rawSearch: '',
    setRawSearch: vi.fn(),
    debounced: '',
    sortKey: 'added_at',
    sortDir: 'desc',
    setSortKey: vi.fn(),
    setSortDir: vi.fn(),
    onPlay: vi.fn(),
    currentTrackId: null,
  };
}

async function renderBesidePlayer(rows: CategoryTrack[]) {
  await page.viewport(1280, 900);
  const { container } = render(
    <MantineProvider theme={clouderTheme} defaultColorScheme="light">
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/categories/s1/c1?fresh=0']}>
          <div style={{ width: 792 }}>
            <TracksTab {...props(rows)} />
          </div>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
  return container.querySelector('table')!;
}

/** Cells whose content spills into the next column. */
function spilling(table: HTMLTableElement): string[] {
  return [...table.querySelectorAll('tbody td')]
    .filter((td) => td.scrollWidth > td.clientWidth + 1)
    .map((td) => td.textContent ?? '');
}

describe('TracksTab desktop table — layout (browser)', () => {
  beforeEach(() => localStorage.clear());

  test('rows are one height whatever they hold: names truncate, tags stay on one line', async () => {
    const table = await renderBesidePlayer(items);
    const rows = [...table.querySelectorAll('tbody tr')];
    expect(rows).toHaveLength(3);
    const heights = rows.map((r) => r.getBoundingClientRect().height);
    // within the last row's missing border; a wrapped line would add ~18px
    for (const h of heights) expect(Math.abs(h - heights[0]!)).toBeLessThan(1);
    // one title line + one mix line, not wrapped text
    expect(heights[0]).toBeLessThan(70);

    // the long title truncates, with room to read it
    const title = [...rows[0]!.querySelectorAll('p')].find((p) =>
      p.textContent?.startsWith('An Extremely'),
    )!;
    expect(title.scrollWidth).toBeGreaterThan(title.clientWidth);
    expect(title.clientWidth).toBeGreaterThanOrEqual(100);

    // four tags + "+2" on one line
    const pills = ['5', 'p5', 'RG', 'VM', '+2'].map((name) =>
      [...rows[0]!.querySelectorAll('span')].find((s) => s.textContent === name)!,
    );
    const tops = pills.map((p) => p.getBoundingClientRect().top);
    for (const top of tops) expect(Math.abs(top - tops[0]!)).toBeLessThan(1);
    // ...and "In playlist" keeps its full width instead of shrinking to make room
    const badge = [...rows[0]!.querySelectorAll('span')].find(
      (s) => s.textContent === 'In playlist',
    )!;
    expect(badge.scrollWidth).toBeLessThanOrEqual(badge.clientWidth);

    // too wide for 792px: the table scrolls in its own box, the page does not
    const box = table.parentElement!;
    expect(box.getBoundingClientRect().width).toBeLessThanOrEqual(792.5);
    expect(box.scrollWidth).toBeGreaterThan(box.clientWidth);
    expect(spilling(table)).toEqual([]);
  });

  test('typical rows with the default columns fit beside the player', async () => {
    const table = await renderBesidePlayer([
      // in a playlist, with a full page of comments: the widest tags and comments cells
      mk(0, {
        used_in_playlist: true,
        comment_count: 100,
        tags: ['Groovy'].map((name, i) => ({ id: `g${i}`, name, color: null })),
      }),
      mk(1, { tags: ['5', 'p3', 'U'].map((name, i) => ({ id: `g${i}`, name, color: null })) }),
    ]);
    const headers = [...table.querySelectorAll('thead th')].map((th) => th.textContent);
    expect(headers).not.toContain('Length');
    expect(headers.some((h) => h?.startsWith('Added'))).toBe(true);
    expect(table.getBoundingClientRect().width).toBeLessThanOrEqual(792.5);
    expect(spilling(table)).toEqual([]);
  });
});
