import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, test, vi } from 'vitest';
import '../../../../i18n';
import { weekOfDate } from '../../../../lib/saturdayWeek';
import { clouderTheme } from '../../../../theme';
import { AUTO_INGEST_KEY } from '../../hooks/useAutoIngest';
import { AdminCoveragePage } from '../AdminCoveragePage';

// Repo convention for browser tests: replace api/client (no msw). It never answers, so a page
// without seeded data stays loading: that is the ghost.
vi.mock('../../../../api/client', () => ({ api: vi.fn(() => new Promise(() => {})) }));

afterEach(() => localStorage.clear());

const ago = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
const queue = { waiting_messages: 0, in_flight: 0, delayed: 0 };
const year = weekOfDate(new Date())[0];

function loadedClient() {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  qc.setQueryData(['admin', 'coverage', year], {
    week_year: year,
    weeks_in_year: 52,
    styles: ['Funky House', 'Mainstage', 'Tech House', 'Afro House'].map((name, i) => ({
      style_id: i + 1,
      clouder_style_id: `s${i}`,
      style_name: name,
      is_hidden: false,
      cells: [],
    })),
  });
  qc.setQueryData(AUTO_INGEST_KEY, {
    settings: {
      enabled: true, mode: 'random', fixed_times: ['09:00'], runs_per_day: 3, timezone: 'UTC',
      periods_per_run: 3, backfill_floor: '2026-01-03', updated_at: '2026-10-07T10:00:00+00:00',
    },
    planned_runs: [ago(-1), ago(-7), ago(-13)],
    last_run: {
      at: ago(4), manual: false, ok: true,
      pairs: [1, 2, 3].map((id) => ({ style_id: id, week_year: 2026, week_number: 38, ok: true, item_count: 300 })),
    },
    due_week: { week_year: 2026, week_number: 39 },
    stuck: [],
    running: false,
  });
  qc.setQueryData(['admin', 'spotifySearchStatus'], {
    status: 'idle', paused_until: null, queue,
    tracks: { total: 4_600, found: 4_410, not_found: 180, waiting: 0, no_isrc: 10, searched_last_10_min: 0 },
  });
  qc.setQueryData(['admin', 'youtubeSearchStatus'], {
    status: 'idle', paused_until: null, queue,
    tracks: { total: 4_600, waiting: 255, searched_last_10_min: 0 },
    results: { matched: 3_400, needs_review: 940, not_found: 3, error: 2, videos: 1_200 },
  });
  const analyzer = (name: string, ai: number) => ({
    name, due: 0, leased: 0, ok: 3_300, ai_detected: ai, failed: 12, unusable_source: 3, last_result_at: ago(0.1),
  });
  qc.setQueryData(['admin', 'analysisStatus'], {
    last_claim_at: ago(0.1),
    last_result_at: ago(0.1),
    analyzers: [analyzer('ai_deezer', 96), analyzer('ai_lofcz', 58), analyzer('light_profile', 0)],
    pair: { high: 41, medium: 17, low: 55, clean: 3_241 },
    queue: { total: 3_400, waiting: 30, in_progress: 1, failed: 12, unusable: 3 },
    profile: { total: 3_400, waiting: 1_240, in_progress: 20, profiled: 2_135, failed: 4, unusable: 1 },
    models: {
      count: 2,
      last_trained_at: ago(48),
      items: ['Afro House', 'Melodic House & Techno'].map((style, i) => ({
        user_id: `u${i}`, user_name: 'Demo DJ', style_id: `s${i}`, style_name: style, version: 2,
        trained_at: ago(48), retrain_pending: false, labels_since_training: 10, n_labels: 310,
        rows_total: 310, n_keep: 122, keep_auc: 0.776, category_bacc: 0.534, n_classes: 3,
        first_hit: 0.58, first_n: 64, predictions: 2_050, max_rss_mb: 1_400,
      })),
    },
  });
  return qc;
}

function renderPage(width: number, qc: QueryClient) {
  return render(
    <MantineProvider theme={clouderTheme}>
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <div style={{ width }}>
            <AdminCoveragePage />
          </div>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

const blocks = (root: HTMLElement) => {
  const top = root.getBoundingClientRect().top;
  return [...root.querySelectorAll('.mantine-Paper-root, .mantine-ScrollArea-root')].map((el) => {
    const r = el.getBoundingClientRect();
    return [Math.round(r.top - top), Math.round(r.height)];
  });
};

test.each([375, 1100])('the coverage page loads in place of its ghost at %ipx', (width) => {
  const loaded = renderPage(width, loadedClient()); // also remembers the row counts
  const want = blocks(loaded.container);
  loaded.unmount();
  const ghost = renderPage(width, new QueryClient());
  expect(ghost.container.querySelector('[aria-busy]')).not.toBeNull();
  // matrix, 4 auto-ingest cards, 4 pipeline stages, the models table
  expect(want.length).toBeGreaterThanOrEqual(10);
  expect(blocks(ghost.container)).toEqual(want);
});
