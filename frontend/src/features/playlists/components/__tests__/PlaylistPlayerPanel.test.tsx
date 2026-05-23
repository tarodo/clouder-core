import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PlaylistPlayerPanel } from '../PlaylistPlayerPanel';
import type { PlaylistTrack } from '../../lib/playlistTypes';

// Stub usePlayback — mirrors CategoryDetailPage.test.tsx:20-53
const playbackWithTrack = {
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
    source: { type: 'playlist' as const, playlistId: 'p1' },
    tracks: [],
    cursor: 0,
    status: 'playing' as const,
  },
  track: {
    current: {
      id: 't1',
      title: 'Now Playing',
      artists: 'Artist A',
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

const playbackEmpty = {
  ...playbackWithTrack,
  track: { current: null as (typeof playbackWithTrack.track.current) | null, positionMs: 0, durationMs: 0 },
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockPlayback: any = playbackWithTrack;

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => mockPlayback,
}));

vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [{ id: 'tag-1', name: 'Acid', color: 'red' }],
    isLoading: false,
  }),
  TrackTagsPopover: ({ target }: { target: React.ReactNode }) => <>{target}</>,
}));

vi.mock('../../hooks/usePlaylistTrackTag', () => ({
  usePlaylistAddTrackTag: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
  usePlaylistRemoveTrackTag: () => ({ mutateAsync: vi.fn(() => Promise.resolve()) }),
}));

const seedTrack: PlaylistTrack = {
  track_id: 't1',
  position: 0,
  added_at: '2026-01-01T00:00:00Z',
  title: 'Now Playing',
  spotify_id: 'sp1',
  isrc: null,
  length_ms: 200000,
  origin: 'beatport',
  mix_name: null,
  artists: [{ id: 'a1', name: 'Artist A' }],
  label: { id: 'lbl1', name: 'Techno Label' },
  bpm: 140,
  spotify_release_date: null,
  is_ai_suspected: false,
  tags: [{ id: 'tag-1', name: 'Acid', color: 'red' }],
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ui(items: PlaylistTrack[] = [], playback: any = playbackWithTrack) {
  mockPlayback = playback;
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <PlaylistPlayerPanel playlistId="p1" items={items} />
      </MantineProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockPlayback = playbackWithTrack;
  Object.values(playbackWithTrack.controls).forEach((m) => {
    if (typeof m === 'function' && 'mockReset' in m)
      (m as { mockReset: () => void }).mockReset();
  });
});

describe('PlaylistPlayerPanel', () => {
  it('renders now-playing title when a track is current', () => {
    render(ui([seedTrack]));
    expect(screen.getByText('Now Playing')).toBeInTheDocument();
  });

  it('renders the tag cloud (+ add-tag control) when a track is current', () => {
    render(ui([seedTrack]));
    // The "+" add-tag ActionIcon button is rendered by PlayerPanelTagCloud
    expect(screen.getByRole('button', { name: /add tag/i })).toBeInTheDocument();
  });

  it('renders empty state when no track is current', () => {
    render(ui([], playbackEmpty));
    expect(screen.getByText(/pick a track/i)).toBeInTheDocument();
  });
});
