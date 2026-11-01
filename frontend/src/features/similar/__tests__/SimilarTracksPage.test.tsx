import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { testTheme } from '../../../test/theme';
import { SimilarTracksPage } from '../SimilarTracksPage';
import type { EntityTrack } from '../../library/hooks/useEntityTracks';

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
vi.mock('../../playback/usePlayback', () => ({ usePlayback: () => playback }));

const row = (id: string, over: Partial<EntityTrack> = {}) => ({
  id,
  title: `Title ${id}`,
  mix_name: null,
  artists: [{ id: 'art', name: 'Art', ai: null }],
  label: { id: 'lbl', name: `Label ${id}`, ai: null },
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
  ...over,
});

const BODIES: Record<string, object> = {
  s: {
    seed: row('s'),
    profiled: true,
    items: [
      row('k1', { categories: [{ id: 'c1', name: 'Rollers' }] }),
      row('d1', { discarded: true }),
    ],
  },
  b: { seed: row('b'), profiled: true, items: [row('x1')] },
  np: { seed: row('np'), profiled: false, items: [] },
  lonely: { seed: row('lonely'), profiled: true, items: [] },
};

beforeEach(() => {
  vi.clearAllMocks();
  server.use(
    http.get('http://localhost/tracks/:id/similar', ({ params }) =>
      HttpResponse.json(BODIES[params.id as string]!),
    ),
  );
});

function Hop() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate('/similar/b')}>
      hop
    </button>
  );
}

function renderAt(trackId: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MantineProvider theme={testTheme}>
        <MemoryRouter initialEntries={[`/similar/${trackId}`]}>
          <Routes>
            <Route
              path="/similar/:trackId"
              element={
                <>
                  <SimilarTracksPage />
                  <Hop />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const titles = () => screen.getAllByText(/^Title /).map((el) => el.textContent);

describe('SimilarTracksPage', () => {
  it('lists the seed first, then the results with their marks and labels', async () => {
    renderAt('s');
    expect(await screen.findByRole('heading', { name: 'Similar tracks' })).toBeInTheDocument();
    await screen.findByText('Title k1');
    expect(titles().slice(-3)).toEqual(['Title s', 'Title k1', 'Title d1']);
    expect(screen.getByText('Seed')).toBeInTheDocument();
    expect(screen.getByText('Rollers')).toBeInTheDocument();
    expect(screen.getByText('DISCARD')).toBeInTheDocument();
    expect(screen.getByText('Label k1')).toBeInTheDocument(); // the label column
  });

  it('says when the seed has no sound profile yet', async () => {
    renderAt('np');
    expect(await screen.findByText(/no sound profile yet/)).toBeInTheDocument();
  });

  it('says when nothing similar is found in the style', async () => {
    renderAt('lonely');
    expect(await screen.findByText('No similar tracks in this style yet.')).toBeInTheDocument();
  });

  it('a new seed re-mounts the page and rebinds the queue', async () => {
    renderAt('s');
    await screen.findByText('Title k1');
    await userEvent.click(screen.getByRole('button', { name: 'hop' }));
    await screen.findByText('Title x1');
    await waitFor(() =>
      expect(playback.controls.bindQueue).toHaveBeenLastCalledWith(
        expect.objectContaining({
          source: { type: 'entity', kind: 'similar', entityId: 'track:b' },
          tracks: [expect.objectContaining({ id: 'b' }), expect.objectContaining({ id: 'x1' })],
        }),
      ),
    );
  });
});
