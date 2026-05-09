import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router';
import i18n from '../../i18n';
import { testTheme } from '../../test/theme';
import { AuthContext } from '../../auth/AuthProvider';
import { AppShellLayout } from '../_layout';
import type { PlaybackContextValue } from '../../features/playback/PlaybackProvider';
import type { PlaybackTrack, QueueStatus } from '../../features/playback/lib/types';

const auth = {
  state: {
    status: 'authenticated' as const,
    user: { id: 'u', spotify_id: 's', display_name: 'Roman', is_admin: false },
    expiresAt: Date.now() + 1_800_000,
    spotifyAccessToken: 'SPTOK' as string | null,
  },
  signIn: () => {},
  signOut: async () => {},
  refresh: async () => false,
};

// Default mock playback: idle queue. Individual tests override via
// `mockPlaybackValue` to drive chrome behavior without touching the real SDK.
let mockPlaybackValue: PlaybackContextValue = makeIdlePlayback();

function makeIdlePlayback(): PlaybackContextValue {
  return {
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    controls: {
      play: vi.fn().mockResolvedValue(undefined),
      pause: vi.fn().mockResolvedValue(undefined),
      togglePlayPause: vi.fn().mockResolvedValue(undefined),
      next: vi.fn().mockResolvedValue(undefined),
      prev: vi.fn().mockResolvedValue(undefined),
      seekMs: vi.fn().mockResolvedValue(undefined),
      seekPct: vi.fn().mockResolvedValue(undefined),
      bindQueue: vi.fn(),
      clearQueue: vi.fn(),
      cancelPendingAdvance: vi.fn(),
      prewarm: vi.fn().mockResolvedValue(undefined),
      openSpotifyExternal: vi.fn(),
    },
    devices: {
      list: [],
      active: null,
      cloderTabId: null,
      isLoading: false,
      error: null,
      isOpen: false,
      pickerAnchor: null,
      open: vi.fn(),
      close: vi.fn(),
      refresh: vi.fn().mockResolvedValue(undefined),
      pick: vi.fn().mockResolvedValue(undefined),
    },
  };
}

function makeActivePlayback(
  status: QueueStatus,
  track: PlaybackTrack,
): PlaybackContextValue {
  const base = makeIdlePlayback();
  return {
    ...base,
    queue: {
      source: { type: 'bucket', blockId: 'B1', bucketId: 'U1' },
      tracks: [track],
      cursor: 0,
      status,
    },
    track: { current: track, positionMs: 0, durationMs: track.duration_ms },
  };
}

vi.mock('../../features/playback/PlaybackProvider', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../features/playback/PlaybackProvider')>();
  return {
    ...actual,
    PlaybackProvider: ({ children }: { children: React.ReactNode }) => (
      <actual.PlaybackContext.Provider value={mockPlaybackValue}>
        {children}
      </actual.PlaybackContext.Provider>
    ),
  };
});

function renderAt(url: string) {
  const router = createMemoryRouter(
    [
      {
        element: <AppShellLayout />,
        children: [
          { path: '/', element: <div data-testid="outlet">HOME</div> },
          { path: '/tracks', element: <div data-testid="outlet">TRACKS</div> },
          {
            path: '/curate/:styleId/:blockId/:bucketId',
            element: <div data-testid="outlet">CURATE</div>,
          },
        ],
      },
    ],
    { initialEntries: [url] },
  );
  return render(
    <I18nextProvider i18n={i18n}>
      <MantineProvider theme={testTheme}>
        <AuthContext.Provider value={auth}>
          <RouterProvider router={router} />
        </AuthContext.Provider>
      </MantineProvider>
    </I18nextProvider>,
  );
}

beforeEach(() => {
  mockPlaybackValue = makeIdlePlayback();
});

describe('AppShellLayout', () => {
  it('renders wordmark + UserMenu + outlet', () => {
    renderAt('/');
    expect(screen.getByText('CLOUDER')).toBeInTheDocument();
    expect(screen.getByText('Roman')).toBeInTheDocument();
    expect(screen.getByTestId('outlet')).toBeInTheDocument();
  });

  it('renders navigation items', () => {
    renderAt('/');
    expect(screen.getAllByRole('link', { name: /home/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /categories/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /triage/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /curate/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /profile/i }).length).toBeGreaterThan(0);
  });
});

describe('AppShellLayout admin nav', () => {
  it('shows Admin nav link for is_admin: true', () => {
    const adminAuth = {
      ...auth,
      state: {
        ...auth.state,
        user: { ...auth.state.user, is_admin: true },
      },
    };
    const router = createMemoryRouter(
      [
        {
          element: <AppShellLayout />,
          children: [{ path: '/', element: <div data-testid="outlet">HOME</div> }],
        },
      ],
      { initialEntries: ['/'] },
    );
    render(
      <I18nextProvider i18n={i18n}>
        <MantineProvider theme={testTheme}>
          <AuthContext.Provider value={adminAuth}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </MantineProvider>
      </I18nextProvider>,
    );
    expect(screen.getAllByRole('link', { name: /admin/i }).length).toBeGreaterThan(0);
  });

  it('does not show Admin nav link for is_admin: false', () => {
    renderAt('/');
    expect(screen.queryByRole('link', { name: /admin/i })).toBeNull();
  });
});

describe('AppShellLayout playback chrome', () => {
  const track: PlaybackTrack = {
    id: 'T1',
    title: 'Song One',
    artists: 'Artist',
    cover_url: null,
    duration_ms: 180_000,
    spotify_id: 'spT1',
  };

  it('does not render MiniBar when queue is idle', () => {
    mockPlaybackValue = makeIdlePlayback();
    renderAt('/');
    expect(
      screen.queryByRole('region', { name: /now playing/i }),
    ).toBeNull();
  });

  it('renders MiniBar on non-PlayerCard route when queue is active', () => {
    mockPlaybackValue = makeActivePlayback('playing', track);
    renderAt('/tracks');
    expect(
      screen.getByRole('region', { name: /now playing/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('Song One')).toBeInTheDocument();
  });

  it('does not render MiniBar on Curate session route when queue is active', () => {
    mockPlaybackValue = makeActivePlayback('playing', track);
    renderAt('/curate/x/B1/U1');
    expect(
      screen.queryByRole('region', { name: /now playing/i }),
    ).toBeNull();
  });
});
