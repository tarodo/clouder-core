// frontend/src/features/curate/components/__tests__/CurateSession.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { CurateSession } from '../CurateSession';

const playMock = vi.fn(async () => {});
const togglePlayPauseMock = vi.fn(async () => {});
const bindQueueMock = vi.fn();

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' as const },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    controls: {
      play: playMock,
      pause: vi.fn(async () => {}),
      togglePlayPause: togglePlayPauseMock,
      next: vi.fn(async () => {}),
      prev: vi.fn(async () => {}),
      seekMs: vi.fn(async () => {}),
      seekPct: vi.fn(async () => {}),
      bindQueue: bindQueueMock,
      clearQueue: vi.fn(),
      cancelPendingAdvance: vi.fn(),
      openSpotifyExternal: vi.fn(),
    },
  }),
}));

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

const block = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS' as const,
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 1 },
    {
      id: 'dst1',
      bucket_type: 'STAGING' as const,
      inactive: false,
      track_count: 0,
      category_id: 'c1',
      category_name: 'Big Room',
    },
  ],
};

function tracksPage(ids: string[]) {
  return {
    items: ids.map((id) => ({
      track_id: id,
      title: `Track ${id}`,
      mix_name: null,
      isrc: null,
      bpm: 124,
      length_ms: 360000,
      publish_date: '2026-04-15',
      spotify_release_date: '2026-04-15',
      spotify_id: `sp-${id}`,
      release_type: 'single',
      is_ai_suspected: false,
      artists: ['Artist A'],
      label_name: 'Label X',
      added_at: '2026-04-21T00:00:00Z',
    })),
    total: ids.length,
    limit: 50,
    offset: 0,
  };
}

function defaultHandlers() {
  return [
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
      HttpResponse.json(tracksPage(['t1'])),
    ),
  ];
}

function renderSession() {
  const qc = makeClient();
  return render(
    <MemoryRouter initialEntries={['/curate/s1/b1/src']}>
      <QueryClientProvider client={qc}>
        <MantineProvider theme={testTheme}>
          <Routes>
            <Route
              path="/curate/:styleId/:blockId/:bucketId"
              element={<CurateSession styleId="s1" blockId="b1" bucketId="src" />}
            />
          </Routes>
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('CurateSession with PlayerCard', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    playMock.mockClear();
    togglePlayPauseMock.mockClear();
    bindQueueMock.mockClear();
    server.use(...defaultHandlers());
  });
  afterEach(() => {
    tokenStore.set(null);
  });

  it('renders PlayerCard at the top of the session', async () => {
    renderSession();
    // CurateCard appears once data loads
    await screen.findByTestId('curate-card');
    // PlayerCard's "Now Playing" eyebrow text identifies it.
    expect(screen.getByText(/now playing/i)).toBeInTheDocument();
    // Sanity: the curate-session container is mounted.
    expect(screen.getByTestId('curate-session')).toBeInTheDocument();
  });

  it('CurateCard onPlay calls playback.controls.play with currentIndex', async () => {
    renderSession();
    await screen.findByTestId('curate-card');
    // CurateCard's Play button (within the card, distinguished from PlayerCard's
    // central control via aria-label "Play"). Both have the same aria-label;
    // CurateCard's button is the only one inside data-testid="curate-card".
    const card = screen.getByTestId('curate-card');
    const playButton = await waitFor(() =>
      within(card).getByRole('button', { name: /^play$/i }),
    );
    await userEvent.click(playButton);
    expect(playMock).toHaveBeenCalled();
    // CurateSession passes the currentIndex (0 for the first track).
    expect(playMock).toHaveBeenCalledWith(0);
  });
});
