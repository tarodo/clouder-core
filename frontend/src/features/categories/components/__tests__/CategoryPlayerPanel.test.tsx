import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router';
import { render, screen, waitFor, within } from '@testing-library/react';
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

const moveMut = vi.hoisted(() =>
  vi.fn((_: { trackId: string; fromCategoryId: string; toCategoryId: string }) => Promise.resolve()),
);

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
vi.mock('../../hooks/useMoveTrackBetweenCategories', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useMoveTrackBetweenCategories: () => ({ mutateAsync: moveMut }),
}));
vi.mock('../../hooks/useCategoriesByStyle', () => ({
  useCategoriesByStyle: () => ({
    data: {
      items: [
        { id: 'c1', name: 'Opening' },
        { id: 'c2', name: 'Journey' },
        { id: 'c3', name: 'Afterhours' },
      ],
    },
    isLoading: false,
  }),
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

function ui(items: CategoryTrack[] = [], phone = false) {
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <MemoryRouter>
          <CategoryPlayerPanel categoryId="c1" styleId="s1" items={items} phone={phone} />
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
  moveMut.mockClear();
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

  it('marks the AI reputation of the artists and the label in the player', () => {
    const rep = (level: 1 | 2 | 3) => ({ level, ai: 1, checked: 2, total: 3 });
    render(ui([{
      ...placedTrack,
      artists: [{ id: 'a1', name: 'A', ai: rep(2) }],
      label: { id: 'l1', name: 'Lbl', ai: rep(3) },
    }]));
    const player = document.querySelector('[data-state]') as HTMLElement;
    expect(within(player).getByLabelText('AI level 2')).toBeInTheDocument();
    expect(within(player).getByLabelText('AI level 3')).toBeInTheDocument();
  });

  it('shows the key of the playing track', () => {
    render(ui([{ ...placedTrack, key_camelot: '8A' }]));
    expect(screen.getByText('8A')).toBeInTheDocument();
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

  it('desktop: no Remove-from-category button (Z does it)', () => {
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

describe('CategoryPlayerPanel on a phone', () => {
  it('drops the label and artist cards', () => {
    render(ui([{ ...placedTrack, label: { id: 'l1', name: 'Lbl' } }], true));
    expect(screen.queryByTestId('label-tile')).not.toBeInTheDocument();
    expect(screen.queryByTestId('artists-panel')).not.toBeInTheDocument();
  });

  it('a tap on another category moves the track there and plays the next; U moves it back', async () => {
    render(ui([placedTrack], true));
    // its own category is not offered
    expect(screen.queryByRole('button', { name: 'Opening' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Journey' }));
    await waitFor(() =>
      expect(moveMut).toHaveBeenCalledWith({ trackId: 't1', fromCategoryId: 'c1', toCategoryId: 'c2' }),
    );
    await waitFor(() => expect(playback.controls.next).toHaveBeenCalledOnce());
    expect(await screen.findByText('Moved to Journey.')).toBeInTheDocument();

    await userEvent.keyboard('u');
    await waitFor(() =>
      expect(moveMut).toHaveBeenLastCalledWith({ trackId: 't1', fromCategoryId: 'c2', toCategoryId: 'c1' }),
    );
  });

  it('a failed move says so and stays on the track', async () => {
    moveMut.mockRejectedValueOnce(new Error('boom'));
    render(ui([placedTrack], true));
    await userEvent.click(screen.getByRole('button', { name: 'Afterhours' }));
    expect(await screen.findByText('Move failed.')).toBeInTheDocument();
    expect(playback.controls.next).not.toHaveBeenCalled();
  });

  it('Remove from category drops the track and plays the next', async () => {
    render(ui([placedTrack], true));
    await userEvent.click(screen.getByRole('button', { name: /remove from category/i }));
    await waitFor(() =>
      expect(categoryMut.remove).toHaveBeenCalledWith({ categoryId: 'c1', trackId: 't1' }),
    );
    await waitFor(() => expect(playback.controls.next).toHaveBeenCalledOnce());
  });

  it('a track that is not in this list gets no category buttons', () => {
    render(ui([], true));
    expect(screen.queryByRole('button', { name: /remove from category/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Journey' })).not.toBeInTheDocument();
  });
});
