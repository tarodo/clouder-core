import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, test, vi } from 'vitest';
import i18n from '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { tzOffsetMin } from '../../../analytics/hooks/useAnalytics';
import { HomePage } from '../HomePage';

// Repo convention for browser tests: replace api/client (no msw). It never answers, so a page
// without seeded data stays loading: that is the ghost.
vi.mock('../../../../api/client', () => ({ api: vi.fn(() => new Promise(() => {})) }));

afterEach(() => localStorage.clear());

const qs = `tz_offset_min=${tzOffsetMin()}`;
const block = (id: string, style: string) => ({
  id,
  style_id: 's1',
  style_name: style,
  name: `2026-W40 · ${style}`,
  date_from: '2026-10-03',
  date_to: '2026-10-09',
  status: 'IN_PROGRESS',
  created_at: '2026-10-03T00:00:00Z',
  updated_at: `2026-10-0${id}T00:00:00Z`,
  finalized_at: null,
  track_count: 30,
});
const cell = { n: 1_380, p50_ms: 9_000, p90_ms: 31_000 };

function loadedClient() {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  qc.setQueryData(['styles'], {
    items: [{ id: 's1', name: 'Afro House' }],
    total: 1,
    limit: 200,
    offset: 0,
  });
  qc.setQueryData(
    ['home', 'activeBlocks', 's1'],
    [block('3', 'Afro House'), block('2', 'Melodic House & Techno')],
  );
  const totals = { listened_ms: 58 * 60_000, tracks: 18 };
  qc.setQueryData(['analytics', 'listening', qs], {
    today: '2026-10-08',
    totals: { day: totals, week: totals, month: totals },
    daily: Array.from({ length: 30 }, (_, i) => ({
      dt: `2026-09-${String(i + 1).padStart(2, '0')}`,
      ...totals,
    })),
  });
  qc.setQueryData(['analytics', 'funnel', qs], {
    today: '2026-10-08',
    stages: [
      { stage: 'triaged', day: 10, week: 912, month: 3_000 },
      { stage: 'categorized', day: 2, week: 206, month: 700 },
      { stage: 'playlisted', day: 1, week: 64, month: 200 },
    ],
  });
  qc.setQueryData(['analytics', 'time-per-track', `${qs}&days=30`], {
    days: 30,
    stages: ['triage', 'category', 'playlist'],
    rows: [
      { style_id: '*', style_name: null, cells: { triage: cell, category: cell, playlist: cell } },
      {
        style_id: 'x',
        style_name: 'Funky House',
        cells: { triage: cell, category: cell, playlist: cell },
      },
    ],
  });
  return qc;
}

function renderHome(width: number, qc: QueryClient) {
  return render(
    <MantineProvider theme={clouderTheme}>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <div style={{ width }}>
              <HomePage />
            </div>
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

const cards = (root: HTMLElement) =>
  [...root.querySelectorAll('.mantine-Card-root')].map((c) => c.getBoundingClientRect().height);

test.each([390, 720])(
  'every home block loads in place of a ghost as tall as itself at %ipx',
  (width) => {
    const loaded = renderHome(width, loadedClient()); // also remembers the row counts
    const want = cards(loaded.container);
    loaded.unmount();
    const ghost = renderHome(width, new QueryClient());
    expect(ghost.container.querySelector('[aria-busy]')).not.toBeNull();
    expect(want).toHaveLength(7); // hero, two counters, active blocks, three analytics cards
    expect(cards(ghost.container)).toEqual(want);
  },
);
