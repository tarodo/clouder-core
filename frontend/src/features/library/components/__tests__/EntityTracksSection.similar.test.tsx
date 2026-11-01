import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import { EntityTracksSection } from '../EntityTracksSection';

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
  queue: { source: null, tracks: [] as { id: string }[], cursor: 0, status: 'idle' },
  track: { current: null, positionMs: 0, durationMs: 0 },
  sdk: { ready: true, error: null },
  devices: { active: null, cloderTabId: null, open: vi.fn() },
}));
vi.mock('../../../playback/usePlayback', () => ({ usePlayback: () => playback }));

const row = (id: string) => ({
  id,
  title: `Title ${id}`,
  mix_name: null,
  artists: [{ id: 'other', name: 'Other', ai: null }],
  label: { id: 'lbl', name: 'Hinterland', ai: null },
  style: { id: 'st', name: 'DnB' },
  bpm: 174,
  length_ms: 300000,
  key_name: null,
  key_camelot: '8A',
  release_date: '2026-10-20',
  spotify_id: `sp_${id}`,
  ai_verdict: null,
  categories: [],
  playlists: [],
  discarded: false,
});

const STYLES = [
  { id: 'st', name: 'DnB', count: 5 },
  { id: 'st2', name: 'Techno', count: 1 },
];
const asked: (string | null)[] = [];

beforeEach(() => {
  asked.length = 0;
  vi.clearAllMocks();
  server.use(
    http.get('http://localhost/artists/art/tracks', () =>
      HttpResponse.json({ items: [row('own')], total: 1, limit: 50, offset: 0 }),
    ),
    http.get('http://localhost/artists/:id/similar', ({ params, request }) => {
      const style = new URL(request.url).searchParams.get('style_id');
      asked.push(style);
      const styles = params.id === 'art' ? STYLES : STYLES.slice(0, 1);
      const used = styles.find((s) => s.id === (style ?? styles[0]!.id))!;
      return HttpResponse.json({
        profiled: true,
        style: { id: used.id, name: used.name },
        styles,
        items: [row(`near_${used.id}`)],
      });
    }),
  );
});

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.search}</output>;
}

function renderAt(search: string, artistId = 'art') {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MantineProvider theme={testTheme}>
        <MemoryRouter initialEntries={[`/artists/${artistId}${search}`]}>
          <Routes>
            <Route
              path="/artists/:artistId"
              element={
                <>
                  <EntityTracksSection kind="artist" entityId={artistId} />
                  <Where />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('artist page: Tracks | Similar', () => {
  it('opens the similar view and style from the URL', async () => {
    renderAt('?view=similar&style=st2');
    expect(await screen.findByText('Title near_st2')).toBeInTheDocument();
    expect(asked).toEqual(['st2']);
    expect(screen.getByRole('radio', { name: 'Techno' })).toBeChecked();
  });

  it('switches views and styles through the URL', async () => {
    renderAt('');
    expect(await screen.findByText('Title own')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'Similar' }));
    expect(await screen.findByText('Title near_st')).toBeInTheDocument();
    expect(screen.getByTestId('where').textContent).toBe('?view=similar');
    await userEvent.click(screen.getByRole('radio', { name: 'Techno' }));
    expect(await screen.findByText('Title near_st2')).toBeInTheDocument();
    expect(screen.getByTestId('where').textContent).toBe('?view=similar&style=st2');
    await userEvent.click(screen.getByRole('radio', { name: 'Tracks' }));
    expect(await screen.findByText('Title own')).toBeInTheDocument();
    expect(screen.getByTestId('where').textContent).toBe('');
  });

  it('shows no style picker for an artist in one style', async () => {
    renderAt('?view=similar', 'solo');
    expect(await screen.findByText('Title near_st')).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'DnB' })).not.toBeInTheDocument();
  });
});
