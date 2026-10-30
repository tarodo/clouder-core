import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CategoryPlayerPanel } from '../CategoryPlayerPanel';
import { undoStack } from '../../hooks/useUndoStack';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';

const categoryMut = vi.hoisted(() => ({
  remove: vi.fn((_: { categoryId: string; trackId: string }) => Promise.resolve()),
  add: vi.fn((_: { categoryId: string; trackId: string }) => Promise.resolve()),
}));

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
      items: [{ id: 'pl-1', name: 'Acid', status: 'active', track_count: 7 }],
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
  useRemoveTrackOptimistic: () => ({ mutateAsync: categoryMut.remove }),
}));
vi.mock('../../hooks/useAddTrackToCategory', () => ({
  useAddTrackToCategory: () => ({ mutateAsync: categoryMut.add }),
}));
vi.mock('../../../library/components/LabelTile', () => ({
  LabelTile: () => <div data-testid="label-tile" />,
}));
vi.mock('../../../library/components/ArtistsPanel', () => ({
  ArtistsPanel: () => <div data-testid="artists-panel" />,
}));
vi.mock('../../../playlists/components/CommentsPanel', () => ({
  CommentsPanel: ({ trackId }: { trackId: string }) => (
    <div data-testid="comments-panel">{trackId}</div>
  ),
}));

function ui(items: CategoryTrack[] = []) {
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <MemoryRouter>
          <CategoryPlayerPanel categoryId="c1" items={items} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>
  );
}

const placedTrack: CategoryTrack = {
  id: 't1', title: 'X', mix_name: null, artists: [{ id: 'a1', name: 'A' }],
  label: null, bpm: null, length_ms: 200000,
  publish_date: null, spotify_release_date: null, isrc: null,
  spotify_id: 'sp1', release_type: null,
  used_in_playlist: false, added_at: '2026-10-02 10:15:00.5',
  source_triage_block_id: 'blk-1', tags: [],
};

beforeEach(() => {
  undoStack.clear();
  categoryMut.remove.mockClear();
  categoryMut.add.mockClear();
  Object.values(playback.controls).forEach((m) => {
    if ('mockReset' in m) (m as { mockReset: () => void }).mockReset();
  });
});

describe('CategoryPlayerPanel', () => {
  it('renders the current track title', () => {
    render(ui());
    expect(screen.getByText('X')).toBeInTheDocument();
  });

  it('the player links the artists and the label to their pages', () => {
    render(ui([{ ...placedTrack, label: { id: 'l1', name: 'Lbl' } }]));
    expect(screen.getByRole('link', { name: 'A' })).toHaveAttribute('href', '/artists/a1');
    expect(screen.getByRole('link', { name: 'Lbl' })).toHaveAttribute('href', '/labels/l1');
  });

  it("a track missing from the list never shows the previous track's label", () => {
    const { rerender } = render(ui([{ ...placedTrack, label: { id: 'l1', name: 'Lbl' } }]));
    expect(screen.getByRole('link', { name: 'Lbl' })).toBeInTheDocument();
    const prev = playback.track.current;
    playback.track.current = { ...prev, id: 't2', title: 'Y' };
    try {
      rerender(ui([]));
      expect(screen.getByText('Y')).toBeInTheDocument();
      expect(screen.queryByText('Lbl')).not.toBeInTheDocument();
    } finally {
      playback.track.current = prev;
    }
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

  it('Z removes the current track from the category and moves on; U puts it back', async () => {
    render(ui([{ ...placedTrack }]));
    await userEvent.keyboard('z');
    await waitFor(() =>
      expect(categoryMut.remove).toHaveBeenCalledWith({ categoryId: 'c1', trackId: 't1' }),
    );
    await waitFor(() => expect(playback.controls.next).toHaveBeenCalledOnce());
    expect(categoryMut.add).not.toHaveBeenCalled();

    await userEvent.keyboard('u');
    await waitFor(() =>
      expect(categoryMut.add).toHaveBeenCalledWith({
        categoryId: 'c1',
        trackId: 't1',
        restore: { added_at: '2026-10-02 10:15:00.5', source_triage_block_id: 'blk-1' },
      }),
    );
  });

  const labeledTrack: CategoryTrack = {
    id: 't1', title: 'X', mix_name: null, artists: [{ id: 'a1', name: 'A' }],
    label: { id: 'lbl1', name: 'L' }, bpm: 120, length_ms: 200000,
    publish_date: null, spotify_release_date: null, isrc: null,
    spotify_id: 'sp1', release_type: null,
    used_in_playlist: false, added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null, tags: [],
  };

  it('renders the comments panel for the current track', () => {
    render(ui());
    const panel = screen.getByTestId('comments-panel');
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent('t1');
  });

  it('renders the LabelTile after the playlists section', () => {
    render(ui([labeledTrack]));
    const playlistsHeading = screen.getByText('Playlists');
    const labelTile = screen.getByTestId('label-tile');
    expect(
      playlistsHeading.compareDocumentPosition(labelTile) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
