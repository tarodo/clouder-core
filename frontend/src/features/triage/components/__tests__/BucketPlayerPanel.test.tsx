import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import type { BucketTrack } from '../../hooks/useBucketTracks';
import type { PlaybackTrack } from '../../../playback/lib/types';

const togglePlayPause = vi.fn();
let current: PlaybackTrack | null = null;

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: { type: 'bucket', blockId: 'b1', bucketId: 'bk1' }, tracks: [], cursor: 0, status: 'playing' },
    track: { current, positionMs: 0, durationMs: 200000 },
    sdk: { ready: true, error: null },
    controls: {
      prewarm: async () => {},
      play: async () => {},
      pause: async () => {},
      togglePlayPause,
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
      list: [], active: null, cloderTabId: null, isLoading: false, error: null,
      isOpen: false, pickerAnchor: null,
      open: () => {}, close: () => {}, refresh: async () => {}, pick: async () => {},
    },
  }),
}));

import { BucketPlayerPanel } from '../BucketPlayerPanel';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const item: BucketTrack = {
  track_id: 't1', title: 'Test Track', mix_name: null, isrc: null, bpm: 124,
  length_ms: 200000, publish_date: null, spotify_release_date: null,
  spotify_id: 'sp1', release_type: null, is_ai_suspected: false,
  artists: ['Artist A'], label_id: null, label_name: 'Anjunadeep',
  added_at: '2026-04-21T00:00:00Z',
};

beforeEach(() => {
  togglePlayPause.mockReset();
  current = null;
});

describe('BucketPlayerPanel', () => {
  it('shows the empty state when nothing is playing', () => {
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.getByText(/Pick a track to start playing/i)).toBeInTheDocument();
  });

  it('renders the current track and label meta when playing', () => {
    current = {
      id: 't1', title: 'Test Track', artists: 'Artist A',
      duration_ms: 200000, spotify_id: 'sp1', cover_url: null,
    };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.getByText('Test Track')).toBeInTheDocument();
    expect(screen.getByText('Anjunadeep')).toBeInTheDocument();
  });
});
