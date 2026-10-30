import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, test, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { EntityTracksSection } from '../EntityTracksSection';

// No msw in the browser runner: the API comes from a mocked api/client.
const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock('../../../../api/client', () => ({ api: apiMock }));

const playback = vi.hoisted(() => ({
  controls: {
    togglePlayPause: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
    seekMs: vi.fn(),
    seekPct: vi.fn(),
    play: vi.fn(),
    prewarm: vi.fn(),
    bindQueue: vi.fn(),
    clearQueue: vi.fn(),
  },
  queue: { source: null, tracks: [], cursor: 0, status: 'paused' },
  track: {
    current: { id: 't1', title: 'Drive Thunder', artists: 'Odessa Marlo', duration_ms: 314000, spotify_id: 'sp1', cover_url: null },
    positionMs: 0,
    durationMs: 314000,
  },
  sdk: { ready: true, error: null },
  devices: { active: null, cloderTabId: null, open: vi.fn() },
}));
vi.mock('../../../playback/usePlayback', () => ({ usePlayback: () => playback }));

const row = (i: number) => ({
  id: `t${i}`,
  title: i === 1 ? 'Drive Thunder' : `Track number ${i} with a longer title`,
  mix_name: 'Extended Mix',
  artists: [{ id: 'a', name: 'Odessa Marlo', ai: null }],
  label: { id: 'l', name: 'Hinterland', ai: null },
  style: { id: 'st', name: 'Melodic House & Techno' },
  bpm: 121,
  length_ms: 314000,
  key_name: null,
  key_camelot: '8B',
  release_date: '2026-10-09',
  spotify_id: `sp${i}`,
  ai_verdict: null,
  categories: i === 1 ? [{ id: 'c1', name: 'Opening' }] : [],
  playlists: [],
});

apiMock.mockImplementation((path: string) =>
  Promise.resolve(
    path.startsWith('/artists/')
      ? { items: [1, 2, 3, 4].map(row), total: 4, limit: 50, offset: 0 }
      : path.startsWith('/styles/')
        ? { items: [{ id: 'c1', name: 'Opening', style_id: 'st', position: 0, track_count: 1 }], total: 1, limit: 200, offset: 0 }
        : path.startsWith('/playlists')
          ? { items: [], total: 0, limit: 100, offset: 0 }
          : { waveform: null },
  ),
);

/** `width`: the page's content column (the viewport minus the app's side menu and padding). */
function renderSection(width?: number) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MantineProvider theme={clouderTheme}>
        <div style={{ width }}>
          <MemoryRouter>
            <EntityTracksSection kind="artist" entityId="a" />
          </MemoryRouter>
        </div>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const box = (el: Element) => el.getBoundingClientRect();

/** Line boxes of an element's text: 2 when it wraps. */
function lines(el: Element): number {
  const range = document.createRange();
  range.selectNodeContents(el);
  return new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size;
}

describe('EntityTracksSection layout', () => {
  test('desktop: the player sits beside the list, dates stay on one line', async () => {
    await page.viewport(1440, 900);
    renderSection(1100);
    const table = await screen.findByRole('table');
    const date = within(table).getAllByText('2026-10-09')[0]!;
    const panel = (await screen.findByText('Categories · Melodic House & Techno')).closest('[data-player]')!;
    expect(box(panel).right).toBeLessThanOrEqual(box(table).left);
    expect(box(panel).width).toBe(442);
    expect(lines(date)).toBe(1);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
  });

  test('phone: the player spans the column above the cards, nothing overflows', async () => {
    await page.viewport(375, 800);
    const { container } = renderSection();
    await screen.findAllByText('2026-10-09');
    const panel = (await screen.findByText('Categories · Melodic House & Techno')).closest('[data-player]')!;
    expect(screen.queryByRole('table')).toBeNull();
    expect(box(panel).width).toBeCloseTo(box(container).width, 0);
    const firstCard = screen.getAllByText(/^Track number/)[0]!;
    expect(box(firstCard).top).toBeGreaterThan(box(panel).bottom);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
  });
});
