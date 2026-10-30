import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider, type InfiniteData } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import { EntityPlayerPanel } from '../EntityPlayerPanel';
import {
  entityTracksKey,
  useEntityTracks,
  type EntityTrack,
  type EntityTracksPage,
} from '../../hooks/useEntityTracks';

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
  queue: {
    source: { type: 'entity', kind: 'artist', entityId: 'art' },
    tracks: [],
    cursor: 0,
    status: 'playing',
  },
  track: {
    current: {
      id: 't2',
      title: 'Harbor',
      artists: 'Art',
      duration_ms: 300000,
      spotify_id: 'sp2',
      cover_url: null,
    } as { id: string } | null,
    positionMs: 0,
    durationMs: 300000,
  },
  sdk: { ready: true, error: null },
  devices: { active: null, cloderTabId: null, open: vi.fn() },
}));
vi.mock('../../../playback/usePlayback', () => ({ usePlayback: () => playback }));

const track = (over: Partial<EntityTrack> = {}): EntityTrack => ({
  id: 't2',
  title: 'Harbor',
  mix_name: 'Original Mix',
  artists: [{ id: 'art', name: 'Art', ai: null }],
  label: { id: 'lbl', name: 'Hinterland', ai: null },
  style: { id: 'st', name: 'Melodic' },
  bpm: 124,
  length_ms: 300000,
  key_name: null,
  key_camelot: '8A',
  release_date: '2026-10-20',
  spotify_id: 'sp2',
  ai_verdict: null,
  categories: [{ id: 'c1', name: 'Peak' }],
  playlists: [{ id: 'p1', name: 'Friday' }],
  ...over,
});

const calls: string[] = [];

function serve() {
  server.use(
    http.get('http://localhost/styles/:styleId/categories', ({ params }) =>
      HttpResponse.json({
        items:
          params.styleId === 'st'
            ? [
                { id: 'c2', name: 'Opening', style_id: 'st', position: 0, track_count: 3 },
                { id: 'c1', name: 'Peak', style_id: 'st', position: 1, track_count: 9 },
              ]
            : [],
        total: 2,
        limit: 200,
        offset: 0,
      }),
    ),
    http.get('http://localhost/playlists', () =>
      HttpResponse.json({
        items: [
          { id: 'p1', name: 'Friday', status: 'active', track_count: 4 },
          { id: 'p2', name: 'Warmup', status: 'active', track_count: 2 },
        ],
        total: 2,
        limit: 100,
        offset: 0,
      }),
    ),
    http.post('http://localhost/categories/:id/tracks', async ({ params, request }) => {
      calls.push(`add ${params.id} ${((await request.json()) as { track_id: string }).track_id}`);
      return HttpResponse.json({ result: 'added' }, { status: 201 });
    }),
    http.delete('http://localhost/categories/:id/tracks/:trackId', ({ params }) => {
      calls.push(`remove ${params.id} ${params.trackId}`);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post('http://localhost/playlists/:id/tracks', ({ params }) => {
      calls.push(`playlist+ ${params.id}`);
      return HttpResponse.json({ added: ['t2'], skipped_duplicates: [], position_after: 1 }, { status: 201 });
    }),
    http.delete('http://localhost/playlists/:id/tracks/:trackId', ({ params }) => {
      calls.push(`playlist- ${params.id}`);
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

/** The page around the panel: the list comes from the (seeded) entity tracks query. */
function Page() {
  const query = useEntityTracks('artist', 'art');
  return (
    <EntityPlayerPanel
      kind="artist"
      entityId="art"
      items={query.data?.pages.flatMap((p) => p.items) ?? []}
    />
  );
}

function renderPanel(row: EntityTrack = track()) {
  // staleTime: the seeded page is the server's answer; nothing refetches it
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const page: EntityTracksPage = { items: [row], total: 1, limit: 50, offset: 0 };
  qc.setQueryData<InfiniteData<EntityTracksPage>>(entityTracksKey('artist', 'art'), {
    pages: [page],
    pageParams: [0],
  });
  render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <Notifications />
        <MemoryRouter>
          <Page />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
  const view = () =>
    qc
      .getQueryData<InfiniteData<EntityTracksPage>>(entityTracksKey('artist', 'art'))!
      .pages.flatMap((p) => p.items);
  return { view };
}

beforeEach(() => {
  calls.length = 0;
  serve();
});
afterEach(() => vi.clearAllMocks());

describe('EntityPlayerPanel', () => {
  it('offers the categories of the track\'s own style, marking the ones it sits in', async () => {
    renderPanel();
    expect(await screen.findByText('Categories · Melodic')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Peak' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Opening' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('the player links the label and the artists to their pages', async () => {
    renderPanel();
    expect(await screen.findByRole('link', { name: 'Hinterland' })).toHaveAttribute('href', '/labels/lbl');
    expect(screen.getByRole('link', { name: 'Art' })).toHaveAttribute('href', '/artists/art');
  });

  it('a tap puts the track into a category, a second takes it out', async () => {
    const { view } = renderPanel();
    await userEvent.click(await screen.findByRole('button', { name: 'Opening' }));
    await waitFor(() => expect(calls).toContain('add c2 t2'));
    expect(view()[0]!.categories.map((c) => c.id)).toEqual(['c1', 'c2']);
    expect(screen.getByRole('button', { name: 'Opening' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Peak' }));
    await waitFor(() => expect(calls).toContain('remove c1 t2'));
    expect(view()[0]!.categories.map((c) => c.id)).toEqual(['c2']);
  });

  it('playlists toggle the same way', async () => {
    const { view } = renderPanel();
    await userEvent.click(await screen.findByRole('button', { name: /Warmup/ }));
    await waitFor(() => expect(calls).toContain('playlist+ p2'));
    await userEvent.click(screen.getByRole('button', { name: /Friday/ }));
    await waitFor(() => expect(calls).toContain('playlist- p1'));
    expect(view()[0]!.playlists.map((p) => p.id)).toEqual(['p2']);
  });

  it('a failed save puts the mark back and says so', async () => {
    server.use(
      http.post('http://localhost/categories/:id/tracks', () =>
        HttpResponse.json({ error_code: 'x', message: 'boom' }, { status: 500 }),
      ),
    );
    const { view } = renderPanel();
    await userEvent.click(await screen.findByRole('button', { name: 'Opening' }));
    expect(await screen.findByText('Could not save. Try again.')).toBeInTheDocument();
    expect(view()[0]!.categories.map((c) => c.id)).toEqual(['c1']);
  });

  it('a track without a style gets no categories', async () => {
    renderPanel(track({ style: null }));
    expect(await screen.findByText('This track has no style, so no category fits it.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Peak' })).not.toBeInTheDocument();
  });

  it('a style without categories says so', async () => {
    renderPanel(track({ style: { id: 'other', name: 'Afro House' } }));
    expect(await screen.findByText('No categories in Afro House yet.')).toBeInTheDocument();
  });
});
