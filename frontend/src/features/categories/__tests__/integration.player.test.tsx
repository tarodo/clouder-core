// frontend/src/features/categories/__tests__/integration.player.test.tsx
//
// Cross-module integration test for the Category Player flow:
//   render SPA at category player route → hotkey "1" adds current track to first
//   playlist → toast appears → hotkey "U" undoes → toast hides.
//
// Pragmatic fallback (acknowledged in the Task 20 plan): jsdom can't drive the
// Spotify Web Playback SDK end-to-end (no Audio backend, no real device-ready),
// so `playback.track.current` never gets populated from a real `play()` chain.
// Instead, we mock `usePlayback` to provide a stable `track.current = t1` and
// `queue.source = { type: 'category', categoryId: 'cat-1' }` so the panel's
// hotkey gate is `active = true`. Everything else is real: the SPA route, the
// CategoryPlayerPanel component, useCategoryPlayerHotkeys, the undoStack, the
// mutation hooks (useAddTracksToPlaylist / useRemoveTrackFromPlaylist), MSW-
// backed network IO, and Mantine notifications.
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import { testTheme } from '../../../test/theme';
import { undoStack } from '../hooks/useUndoStack';

// Pragmatic fallback (see file header): stub usePlayback so the panel renders
// with a known current track. The queue source matches the route's categoryId
// so the hotkey gate inside useCategoryPlayerHotkeys is `active = true`.
vi.mock('../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: {
      source: { type: 'category' as const, categoryId: 'cat-1', styleId: 's1' },
      tracks: [],
      cursor: 0,
      status: 'playing' as const,
    },
    track: {
      current: {
        id: 't1',
        title: 'Track A',
        artists: 'X',
        duration_ms: 200000,
        spotify_id: 'sp1',
        cover_url: null,
      },
      positionMs: 0,
      durationMs: 200000,
    },
    sdk: { ready: true, error: null },
    controls: {
      prewarm: async () => {},
      play: async () => {},
      pause: async () => {},
      togglePlayPause: async () => {},
      next: async () => {},
      prev: async () => {},
      seekMs: async () => {},
      seekPct: async () => {},
      bindQueue: () => {},
      clearQueue: () => {},
      cancelPendingAdvance: () => {},
      openSpotifyExternal: () => {},
    },
    devices: {
      list: [],
      active: null,
      cloderTabId: null,
      isLoading: false,
      error: null,
      isOpen: false,
      pickerAnchor: null,
      open: () => {},
      close: () => {},
      refresh: async () => {},
      pick: async () => {},
    },
  }),
}));

// Now we can import the route — its imports of usePlayback resolve to the mock.
import { CategoryPlayerPage } from '../routes/CategoryPlayerPage';

interface AddTracksBody {
  track_ids: string[];
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [{ path: '/categories/:styleId/:id/player', element: children }],
    { initialEntries: ['/categories/s1/cat-1/player'] },
  );
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
  undoStack.clear();
  notifications.clean();
});

afterEach(() => {
  undoStack.clear();
  notifications.clean();
});

describe('Category player — integration', () => {
  it('hotkey 1 adds current track to first playlist; toast appears; U undoes; toast hides', async () => {
    const addCalls: AddTracksBody[] = [];
    const deleteCalls: string[] = [];

    server.use(
      http.get('http://localhost/categories/cat-1', () =>
        HttpResponse.json({
          id: 'cat-1',
          name: 'House',
          style_id: 's1',
          style_name: 'House',
          track_count: 1,
        }),
      ),
      http.get('http://localhost/categories/cat-1/tracks', () =>
        HttpResponse.json({
          items: [
            {
              id: 't1',
              title: 'Track A',
              mix_name: null,
              artists: [{ id: 'a', name: 'X' }],
              label: null,
              bpm: 120,
              length_ms: 200000,
              publish_date: null,
              spotify_release_date: '2024-01-01',
              isrc: null,
              spotify_id: 'sp1',
              release_type: null,
              is_ai_suspected: false,
              used_in_playlist: false,
              added_at: '2024-01-02',
              source_triage_block_id: null,
              tags: [],
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
      http.get('http://localhost/playlists', () =>
        HttpResponse.json({
          items: [
            { id: 'pl-1', name: 'Acid', status: 'active', track_count: 0 },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        }),
      ),
      http.get('http://localhost/tags', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
      http.post('http://localhost/playlists/pl-1/tracks', async ({ request }) => {
        const body = (await request.json().catch(() => ({}))) as AddTracksBody;
        addCalls.push(body);
        return HttpResponse.json(
          { added: body.track_ids ?? [], skipped_duplicates: [], position_after: 1 },
          { status: 201 },
        );
      }),
      http.delete(
        'http://localhost/playlists/pl-1/tracks/:trackId',
        ({ params }) => {
          deleteCalls.push(params.trackId as string);
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    render(
      <Wrapper>
        <CategoryPlayerPage />
      </Wrapper>,
    );

    // Wait for the player panel to render the current track title.
    await screen.findByText('Track A');
    // Sanity: the playlist list also loaded so the hotkey can resolve index 0.
    // The button shows the playlist name with its track count: "Acid (0)".
    await screen.findByText('Acid (0)');

    // Hotkey "1" → onTogglePlaylistByIndex(0) → onAddPlaylist('pl-1')
    // → POST /playlists/pl-1/tracks with { track_ids: ['t1'] }.
    await userEvent.keyboard('1');
    await waitFor(() => {
      expect(addCalls.length).toBe(1);
    });
    expect(addCalls[0]?.track_ids).toEqual(['t1']);

    // Toast appears with the "Added to playlist" copy.
    const toast = await screen.findByText(/added to playlist/i);
    expect(toast).toBeInTheDocument();

    // Hotkey "U" → undoStack.popAndRun() → useRemoveTrackFromPlaylist mutateAsync
    // → DELETE /playlists/pl-1/tracks/t1.
    await userEvent.keyboard('u');
    await waitFor(() => {
      expect(deleteCalls).toEqual(['t1']);
    });

    // Toast disappears (undoStack cleared → useEffect calls notifications.hide).
    await waitFor(() => {
      expect(screen.queryByText(/added to playlist/i)).not.toBeInTheDocument();
    });
  });
});
