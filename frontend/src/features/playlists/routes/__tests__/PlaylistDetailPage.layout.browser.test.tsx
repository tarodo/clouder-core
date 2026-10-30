import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { expect, test, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { PlaylistDetailPage } from '../PlaylistDetailPage';

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
  queue: { source: null, tracks: [], cursor: 0, status: 'idle' },
  track: { current: null, positionMs: 0, durationMs: 0 },
  sdk: { ready: true, error: null },
  devices: { active: null, cloderTabId: null, open: vi.fn() },
}));
vi.mock('../../../playback/usePlayback', () => ({ usePlayback: () => playback }));

const playlist = {
  id: 'p1',
  user_id: 'u1',
  name: 'Saturday warm-up',
  description: 'First hour: groove before energy.',
  is_public: false,
  cover_s3_key: null,
  cover_url: null,
  cover_uploaded_at: null,
  spotify_playlist_id: null,
  last_published_at: null,
  needs_republish: false,
  ytmusic_playlist_id: null,
  ytmusic_last_published_at: null,
  ytmusic_needs_republish: false,
  track_count: 40,
  status: 'active',
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-09T00:00:00Z',
};

const track = (i: number) => ({
  track_id: `t${i}`,
  position: i,
  added_at: '2026-10-09T00:00:00Z',
  title: `Track ${i}`,
  spotify_id: `sp${i}`,
  isrc: null,
  length_ms: 300000,
  origin: 'beatport',
  mix_name: 'Original Mix',
  artists: [{ id: 'a', name: 'Odessa Marlo' }],
  label: { id: 'l', name: 'Hinterland' },
  bpm: 122,
  spotify_release_date: '2026-09-26',
  tags: [],
});

apiMock.mockImplementation((path: string) =>
  Promise.resolve(
    path.startsWith('/playlists/p1/tracks')
      ? { items: Array.from({ length: 40 }, (_, i) => track(i + 1)), total: 40, limit: 500, offset: 0 }
      : path === '/playlists/p1'
        ? playlist
        : { items: [], total: 0, limit: 100, offset: 0 },
  ),
);

/** The nearest ancestor that scrolls its own content. */
function scroller(el: Element): HTMLElement {
  let node = el.parentElement;
  while (node && getComputedStyle(node).overflowY !== 'auto') node = node.parentElement;
  return node!;
}

test('desktop: the header stays put, the track list scrolls on its own below it', async () => {
  await page.viewport(1440, 900);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MantineProvider theme={clouderTheme}>
        <MemoryRouter initialEntries={['/playlists/p1']}>
          <Routes>
            <Route path="/playlists/:id" element={<PlaylistDetailPage />} />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
  const last = await screen.findByText('Track 40');
  const crumb = screen.getByRole('link', { name: 'Playlists' });
  const search = screen.getByPlaceholderText(/search/i);
  const crumbTop = crumb.getBoundingClientRect().top;
  const searchTop = search.getBoundingClientRect().top;

  // the page itself never scrolls: everything below the header fits the screen
  expect(document.documentElement.scrollHeight).toBeLessThanOrEqual(window.innerHeight);
  expect(last.getBoundingClientRect().top).toBeGreaterThan(window.innerHeight);

  const list = scroller(last);
  list.scrollTop = list.scrollHeight;
  await expect.poll(() => last.getBoundingClientRect().bottom).toBeLessThanOrEqual(window.innerHeight);
  // the header and the list's controls stayed where they were
  expect(crumb.getBoundingClientRect().top).toBe(crumbTop);
  expect(search.getBoundingClientRect().top).toBe(searchTop);
  // the player column ends on screen too
  expect(document.querySelector('[data-player]')!.getBoundingClientRect().bottom).toBeLessThanOrEqual(
    window.innerHeight,
  );
});
