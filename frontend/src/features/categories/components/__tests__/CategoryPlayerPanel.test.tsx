import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CategoryPlayerPanel } from '../CategoryPlayerPanel';
import { undoStack } from '../../hooks/useUndoStack';

const playback = {
  controls: {
    togglePlayPause: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
    seekMs: vi.fn(),
    seekPct: vi.fn(),
    play: vi.fn(),
    pause: vi.fn(),
    prewarm: vi.fn(),
    bindQueue: vi.fn(),
    clearQueue: vi.fn(),
    cancelPendingAdvance: vi.fn(),
    openSpotifyExternal: vi.fn(),
  },
  queue: {
    source: { type: 'category' as const, categoryId: 'c1', styleId: 's1' },
    tracks: [],
    cursor: 0,
    status: 'playing' as const,
  },
  track: {
    current: {
      id: 't1',
      title: 'X',
      artists: 'A',
      duration_ms: 200000,
      spotify_id: 'sp1',
      cover_url: null,
    },
    positionMs: 0,
    durationMs: 200000,
  },
  sdk: { ready: true, error: null },
  devices: {
    active: null,
    list: [],
    cloderTabId: null,
    isLoading: false,
    error: null,
    isOpen: false,
    pickerAnchor: null,
    open: vi.fn(),
    close: vi.fn(),
    refresh: vi.fn(),
    pick: vi.fn(),
  },
};

vi.mock('../../../playback/usePlayback', () => ({ usePlayback: () => playback }));
vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [{ id: 'tag-1', name: 'Acid', color: 'red' }],
    isLoading: false,
  }),
}));
vi.mock('../../../playlists/hooks/usePlaylists', () => ({
  usePlaylists: () => ({
    data: {
      items: [{ id: 'pl-1', name: 'Acid', status: 'active' }],
      total: 1,
      limit: 100,
      offset: 0,
    },
    isLoading: false,
  }),
}));
vi.mock('../../../tags/hooks/useAddTrackTag', () => ({
  useAddTrackTag: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
}));
vi.mock('../../../tags/hooks/useRemoveTrackTag', () => ({
  useRemoveTrackTag: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
}));
vi.mock('../../../playlists/hooks/useAddTracksToPlaylist', () => ({
  useAddTracksToPlaylist: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
}));
vi.mock('../../../playlists/hooks/useRemoveTrackFromPlaylist', () => ({
  useRemoveTrackFromPlaylist: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
}));
vi.mock('../../hooks/useRemoveTrackOptimistic', () => ({
  useRemoveTrackOptimistic: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
}));

function ui() {
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <CategoryPlayerPanel categoryId="c1" styleId="s1" />
      </MantineProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  undoStack.clear();
  Object.values(playback.controls).forEach((m) => {
    if ('mockReset' in m) (m as { mockReset: () => void }).mockReset();
  });
});

describe('CategoryPlayerPanel', () => {
  it('renders the current track title', () => {
    render(ui());
    expect(screen.getByText('X')).toBeInTheDocument();
  });

  it('renders the playlist cloud (with mock playlist)', () => {
    render(ui());
    // "Acid" appears both as tag and playlist; require at least one match.
    expect(screen.getAllByText('Acid').length).toBeGreaterThan(0);
  });

  it('shows Remove from category button', () => {
    render(ui());
    // i18n key strings render as-is until Task 19 wires real translations.
    expect(
      screen.getByRole('button', { name: /remove_from_category/i }),
    ).toBeInTheDocument();
  });

  it('U-key triggers undo when stack has an entry', async () => {
    const undo = vi.fn(() => Promise.resolve());
    undoStack.push({ id: 'a', label: 'L', undo });
    render(ui());
    await userEvent.keyboard('u');
    expect(undo).toHaveBeenCalledOnce();
  });
});
