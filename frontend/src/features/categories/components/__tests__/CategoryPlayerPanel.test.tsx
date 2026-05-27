import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CategoryPlayerPanel } from '../CategoryPlayerPanel';
import { undoStack } from '../../hooks/useUndoStack';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';

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
  TrackTagsPopover: ({ target }: { target: React.ReactNode }) => <>{target}</>,
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
vi.mock('../../../library/components/LabelTile', () => ({
  LabelTile: () => <div data-testid="label-tile" />,
}));
vi.mock('../../../library/components/ArtistsPanel', () => ({
  ArtistsPanel: () => <div data-testid="artists-panel" />,
}));

function ui(items: CategoryTrack[] = []) {
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <CategoryPlayerPanel categoryId="c1" styleId="s1" items={items} />
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

  it('does not render a Remove-from-category button (UI removed)', () => {
    render(ui());
    expect(
      screen.queryByRole('button', { name: /remove from category/i }),
    ).not.toBeInTheDocument();
  });

  it('U-key triggers undo when stack has an entry', async () => {
    const undo = vi.fn(() => Promise.resolve());
    undoStack.push({ id: 'a', label: 'L', undo });
    render(ui());
    await userEvent.keyboard('u');
    expect(undo).toHaveBeenCalledOnce();
  });

  const labeledTrack: CategoryTrack = {
    id: 't1', title: 'X', mix_name: null, artists: [{ id: 'a1', name: 'A' }],
    label: { id: 'lbl1', name: 'L' }, bpm: 120, length_ms: 200000,
    publish_date: null, spotify_release_date: null, isrc: null,
    spotify_id: 'sp1', release_type: null, is_ai_suspected: false,
    used_in_playlist: false, added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null, tags: [],
  };

  it('renders the LabelTile after the playlists section', () => {
    render(ui([labeledTrack]));
    const playlistsHeading = screen.getByText('Playlists');
    const labelTile = screen.getByTestId('label-tile');
    expect(
      playlistsHeading.compareDocumentPosition(labelTile) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
