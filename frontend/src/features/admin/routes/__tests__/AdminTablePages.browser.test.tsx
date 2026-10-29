import { MantineProvider } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, expect, test, vi } from 'vitest';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { AdminArtistEnrichmentBacklogPage } from '../AdminArtistEnrichmentBacklogPage';
import { AdminArtistEnrichmentRunDetailPage } from '../AdminArtistEnrichmentRunDetailPage';
import { AdminArtistEnrichmentRunsPage } from '../AdminArtistEnrichmentRunsPage';
import { AdminAutoEnrichPage } from '../AdminAutoEnrichPage';
import { AdminEnrichmentBacklogPage } from '../AdminEnrichmentBacklogPage';
import { AdminEnrichmentRunDetailPage } from '../AdminEnrichmentRunDetailPage';
import { AdminEnrichmentRunsPage } from '../AdminEnrichmentRunsPage';
import { AdminSpotifyNotFoundPage } from '../AdminSpotifyNotFoundPage';
import { AdminYoutubeReviewPage } from '../AdminYoutubeReviewPage';

// Repo convention for browser tests: replace api/client (no msw). It never answers, so a page
// without seeded data stays loading: that is the ghost.
vi.mock('../../../../api/client', () => ({ api: vi.fn(() => new Promise(() => {})) }));

afterEach(() => localStorage.clear());

const infinite = (items: unknown[], next: string | null) => ({
  pages: [{ items, next_cursor: next, total_estimate: items.length }],
  pageParams: [undefined],
});
const backlogRow = (i: number) => ({
  id: `l${i}`, name: `Label ${i}`, style: 'techno', status: i ? 'completed' : 'none',
  track_count: 10 + i, last_attempted_at: i ? '2026-01-01T00:00:00Z' : null,
});
const runRow = (i: number) => ({
  id: `${i}aaaaaaa-0000-0000-0000-000000000000`, status: 'completed', source: i ? 'auto' : 'manual',
  created_at: '2026-01-01T00:00:00Z', cells_ok: 3, cells_error: 0, cells_total: 3, cost_usd: 0.0042,
});
const run = {
  ...runRow(0), prompt_slug: 'label_v3', prompt_version: 'v1', vendors: ['gemini', 'openai'], cells: [],
};
const options = (vendors: string[]) => ({
  vendors,
  prompt_versions: [{ slug: 'label_v3', version: 'v1', is_default: true }],
  default_models: {},
  merge: { vendor: 'deepseek', default_model: 'deepseek-v4-flash' },
});
const enrichConfig = (vendors: string[]) => ({
  config: {
    enabled: true, vendors: vendors.slice(0, 2), prompt_slug: 'label_v3', prompt_version: 'v1',
    models: {}, merge_vendor: 'deepseek', merge_model: 'deepseek-v4-flash',
  },
  options: options(vendors),
});
const reviewTrack = (i: number) => ({
  track_id: `t${i}`, title: `Track ${i}`, mix_name: 'Extended Mix', artists: 'Artist', length_ms: 360_000,
  spotify_url: null,
  candidates: Array.from({ length: 5 }, (_, j) => ({
    vendor_track_id: `v${i}${j}`, title: `Track ${i} (Extended Mix)`, artists: ['Artist'], album: null,
    duration_ms: 360_000, score: 0.91, url: '#',
  })),
});

const PAGES: [string, string, string, ReactElement, (qc: QueryClient) => void][] = [
  ['label backlog', '/', '/', <AdminEnrichmentBacklogPage />, (qc) =>
    qc.setQueryData(['admin', 'labelBacklog', '', 'all'], infinite([0, 1, 2].map(backlogRow), 'next'))],
  ['artist backlog', '/', '/', <AdminArtistEnrichmentBacklogPage />, (qc) =>
    qc.setQueryData(['admin', 'artistBacklog', '', 'all'], infinite([0, 1].map(backlogRow), null))],
  ['label runs', '/', '/', <AdminEnrichmentRunsPage />, (qc) =>
    qc.setQueryData(['admin', 'enrichmentRuns', 'all', null], infinite([0, 1, 2].map(runRow), null))],
  ['artist runs', '/', '/', <AdminArtistEnrichmentRunsPage />, (qc) =>
    qc.setQueryData(['admin', 'artistEnrichmentRuns', 'all', null], infinite([0, 1].map(runRow), 'n'))],
  ['tracks not on Spotify', '/', '/', <AdminSpotifyNotFoundPage />, (qc) => {
    qc.setQueryData(['admin', 'spotifySearchStatus'], {
      status: 'running', paused_until: null, queue: { waiting_messages: 0, in_flight: 0, delayed: 0 },
      tracks: { total: 4_600, found: 4_410, not_found: 180, waiting: 12, no_isrc: 10, searched_last_10_min: 40 },
    });
    qc.setQueryData(['admin', 'spotifyNotFound', 50, 0, '', null, null], {
      items: [0, 1, 2].map((i) => ({ track_id: `t${i}`, title: `Track ${i}`, artists: ['A', 'B'], isrc: null })),
      total: 3, limit: 50, offset: 0,
    });
  }],
  ['auto-enrich', '/', '/', <AdminAutoEnrichPage />, (qc) => {
    qc.setQueryData(['admin', 'autoEnrich', 'labels'], enrichConfig(['gemini', 'openai', 'tavily_deepseek']));
    qc.setQueryData(['admin', 'autoEnrich', 'artists'], enrichConfig(['openai']));
  }],
  ['label run', '/r/:runId', '/r/run1', <AdminEnrichmentRunDetailPage />, (qc) =>
    qc.setQueryData(['admin', 'enrichmentRun', 'run1'], run)],
  ['artist run', '/r/:runId', '/r/run1', <AdminArtistEnrichmentRunDetailPage />, (qc) =>
    qc.setQueryData(['admin', 'artistEnrichmentRun', 'run1'], run)],
  ['YouTube review', '/', '/?style=1&year=2026&week=40', <AdminYoutubeReviewPage />, (qc) =>
    qc.setQueryData(['admin', 'youtube-review', 1, 2026, 40], {
      style_name: 'Techno', tracks: [0, 1, 2].map(reviewTrack),
    })],
];

function renderPage(width: number, path: string, url: string, page: ReactElement, qc: QueryClient) {
  return render(
    <MantineProvider theme={clouderTheme}>
      <DatesProvider settings={{}}>
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={[url]}>
            <div style={{ width }}>
              <Routes>
                <Route path={path} element={page} />
              </Routes>
            </div>
          </MemoryRouter>
        </QueryClientProvider>
      </DatesProvider>
    </MantineProvider>,
  );
}

const SELECTOR = [
  'table', 'tr', 'h6', '.mantine-Paper-root', '.mantine-Card-root', '.mantine-Button-root',
  '.mantine-Pagination-root', '.mantine-InputWrapper-root', '.mantine-Checkbox-root',
  '.mantine-Switch-root', '.mantine-Badge-root',
].join(', ');
const blocks = (root: HTMLElement) => {
  const top = root.getBoundingClientRect().top;
  return [...root.querySelectorAll(SELECTOR)]
    .map((el) => [el.tagName, el.getBoundingClientRect()] as const)
    .filter(([, r]) => r.height > 0) // a hidden tab
    .map(([tag, r]) => [tag, Math.round(r.top - top), Math.round(r.height)]);
};
const height = (root: HTMLElement) =>
  root.querySelector('div[style*="width"]')!.getBoundingClientRect().height;

test.each(PAGES.flatMap(([name, ...rest]) => [375, 1100].map((w) => [name, w, ...rest] as const)))(
  '%s loads in place of its ghost at %ipx',
  (_name, width, path, url, page, seed) => {
    const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    seed(qc);
    const loaded = renderPage(width, path, url, page, qc); // also remembers the row counts
    const want = blocks(loaded.container);
    const wantHeight = height(loaded.container);
    const table = [...loaded.container.querySelectorAll('table')].some((el) => el.clientHeight > 0);
    loaded.unmount();
    const ghost = renderPage(width, path, url, page, new QueryClient());
    expect(ghost.container.querySelector('[aria-busy]')).not.toBeNull();
    if (table && width < 1100) {
      // A narrow table sizes its columns by their text, so a row wraps by what it holds: the
      // ghost's placeholders can only come close to real names here (exact on wider screens).
      expect(Math.abs(height(ghost.container) - wantHeight) / wantHeight).toBeLessThan(0.25);
    } else {
      expect(blocks(ghost.container)).toEqual(want);
    }
  },
);
