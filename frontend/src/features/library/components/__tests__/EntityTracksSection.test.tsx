import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import { EntityTracksSection } from '../EntityTracksSection';
import type { EntityTrack } from '../../hooks/useEntityTracks';

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

const row = (id: string, released: string, over: Partial<EntityTrack> = {}): EntityTrack => ({
  id,
  title: `Title ${id}`,
  mix_name: null,
  artists: [{ id: 'art', name: 'Art', ai: null }],
  label: { id: 'lbl', name: 'Hinterland', ai: null },
  style: { id: 'st', name: 'Melodic' },
  bpm: 124,
  length_ms: 300000,
  key_name: null,
  key_camelot: '8A',
  release_date: released,
  spotify_id: `sp_${id}`,
  ai_verdict: null,
  categories: [],
  playlists: [],
  ...over,
});

const offsets: string[] = [];
const UNAVAILABLE = 'No Spotify match';

beforeEach(() => {
  offsets.length = 0;
  vi.clearAllMocks();
  server.use(
    http.get('http://localhost/artists/art/tracks', ({ request }) => {
      const offset = new URL(request.url).searchParams.get('offset') ?? '0';
      offsets.push(offset);
      const items =
        offset === '0'
          ? [
              row('t1', '2026-10-20', { categories: [{ id: 'c1', name: 'Peak' }] }),
              row('t2', '2026-09-01', { spotify_id: null, playlists: [{ id: 'p1', name: 'F' }] }),
            ]
          : [row('t3', '2025-01-01')];
      return HttpResponse.json({ items, total: 3, limit: 50, offset: Number(offset) });
    }),
  );
});

function renderSection() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MantineProvider theme={testTheme}>
        <EntityTracksSection kind="artist" entityId="art" />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('EntityTracksSection', () => {
  it('lists the tracks in the order the API sends (newest release first) with what is mine', async () => {
    renderSection();
    expect(await screen.findByText('Tracks · 3')).toBeInTheDocument();
    expect(screen.getAllByText(/^Title t/).map((el) => el.textContent)).toEqual([
      'Title t1',
      'Title t2',
    ]);
    expect(screen.getByText('Peak')).toBeInTheDocument();
    expect(screen.getByText('In 1 playlist')).toBeInTheDocument();
  });

  it('binds the loaded tracks to the player as this artist\'s queue', async () => {
    renderSection();
    await waitFor(() =>
      expect(playback.controls.bindQueue).toHaveBeenLastCalledWith(
        expect.objectContaining({
          source: { type: 'entity', kind: 'artist', entityId: 'art' },
          tracks: [expect.objectContaining({ id: 't1' }), expect.objectContaining({ id: 't2' })],
        }),
      ),
    );
  });

  it('plays a track; one without Spotify cannot be played', async () => {
    renderSection();
    await screen.findByText('Title t1');
    await userEvent.click(screen.getByRole('button', { name: 'Play track' }));
    expect(playback.controls.play).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ id: 't1', spotify_id: 'sp_t1' }),
    );
    expect(screen.getByRole('button', { name: UNAVAILABLE })).toBeDisabled();
  });

  it('shows more on request', async () => {
    renderSection();
    await userEvent.click(await screen.findByRole('button', { name: 'Show more' }));
    expect(await screen.findByText('Title t3')).toBeInTheDocument();
    expect(offsets).toEqual(['0', '2']);
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument();
  });
});
