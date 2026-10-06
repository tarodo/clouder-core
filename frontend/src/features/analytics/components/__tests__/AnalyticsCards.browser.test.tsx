import { Card, MantineProvider, Stack } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, test, vi } from 'vitest';
import i18n from '../../../../i18n';
import { tzOffsetMin } from '../../hooks/useAnalytics';
import { FunnelCard, ListeningCard, TimePerTrackCard } from '../AnalyticsCards';

// Repo convention for browser tests: replace api/client (no msw); data is
// seeded straight into the query cache.
vi.mock('../../../../api/client', () => ({ api: vi.fn() }));

const qs = `tz_offset_min=${tzOffsetMin()}`;
const big = { listened_ms: 99_999 * 60_000, tracks: 12_345 }; // worst-case widths

function renderInColumn(width: number) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  qc.setQueryData(['analytics', 'listening', qs], {
    today: '2026-10-05',
    totals: { day: big, week: big, month: big },
    daily: Array.from({ length: 30 }, (_, i) => ({ dt: `2026-09-${String(i + 1).padStart(2, '0')}`, ...big })),
  });
  qc.setQueryData(['analytics', 'funnel', qs], {
    today: '2026-10-05',
    stages: [
      { stage: 'triaged', day: 1, week: 12_345, month: 99_999 },
      { stage: 'categorized', day: 1, week: 1_234, month: 9_999 },
      { stage: 'playlisted', day: 0, week: 123, month: 999 },
    ],
  });
  const cell = { n: 12_345, p50_ms: 599_000, p90_ms: 599_000 }; // widest: "599s · 12k"
  qc.setQueryData(['analytics', 'time-per-track', `${qs}&days=30`], {
    days: 30,
    stages: ['triage', 'category', 'playlist'],
    rows: [
      { style_id: '*', style_name: null, cells: { triage: cell, category: cell, playlist: cell } },
      {
        style_id: 'x',
        style_name: 'Melodic House & Techno (Progressive Deep Organic)',
        cells: { triage: cell, category: cell, playlist: cell },
      },
    ],
  });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          {/* Home column: Stack maw=720, sibling Card = the other home blocks */}
          <div style={{ width }}>
            <Stack gap="md" maw={720}>
              <Card withBorder padding="md" radius="md" data-testid="sibling">
                block
              </Card>
              <ListeningCard />
              <FunnelCard />
              <TimePerTrackCard />
            </Stack>
          </div>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

function cardOf(testId: string): HTMLElement {
  return screen.getByTestId(testId).closest('.mantine-Card-root') as HTMLElement;
}

test('skeletons are as tall as the loaded cards (no jump on load)', () => {
  const loaded = renderInColumn(720);
  const h = (el: Element | null) => Math.round(el!.getBoundingClientRect().height);
  const listening = h(cardOf('listening-day'));
  const funnel = h(cardOf('funnel-triaged'));
  loaded.unmount();
  render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={new QueryClient()}>
          <div style={{ width: 720 }}>
            <ListeningCard />
            <FunnelCard />
          </div>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
  expect(Math.abs(h(screen.getByTestId('listening-skeleton')) - listening)).toBeLessThanOrEqual(4);
  expect(Math.abs(h(screen.getByTestId('funnel-skeleton')) - funnel)).toBeLessThanOrEqual(4);
});

describe.each([720, 343])('analytics cards in a %ipx home column', (width) => {
  test('match the other home blocks width and do not overflow', () => {
    renderInColumn(width);
    const sibling = screen.getByTestId('sibling').getBoundingClientRect().width;
    for (const card of [cardOf('listening-day'), cardOf('funnel-triaged'), cardOf('tpt-x-triage')]) {
      expect(Math.round(card.getBoundingClientRect().width)).toBe(Math.round(sibling));
      expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth);
    }
  });

  test('time-per-track cells keep their numbers inside the cell', () => {
    renderInColumn(width);
    // Each text line must fit its cell (nowrap text spills over neighbours
    // without widening the card, so check the line boxes themselves).
    for (const id of ['tpt-*-triage', 'tpt-x-category', 'tpt-x-playlist']) {
      for (const line of screen.getByTestId(id).querySelectorAll('p')) {
        expect(line.scrollWidth).toBeLessThanOrEqual(line.clientWidth + 1);
      }
    }
  });

  test('keeps the three listening periods on one row', () => {
    renderInColumn(width);
    const tops = ['day', 'week', 'month'].map(
      (p) => screen.getByTestId(`listening-${p}`).getBoundingClientRect().top,
    );
    expect(new Set(tops.map(Math.round)).size).toBe(1);
    for (const p of ['day', 'week', 'month']) {
      const el = screen.getByTestId(`listening-${p}`);
      expect(el.scrollWidth).toBeLessThanOrEqual(el.clientWidth + 1);
    }
  });
});
