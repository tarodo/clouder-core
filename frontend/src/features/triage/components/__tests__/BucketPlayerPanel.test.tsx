import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '../../../../i18n';
import type { BucketTrack } from '../../hooks/useBucketTracks';
import type { PlaybackTrack } from '../../../playback/lib/types';
import type { TriageBlock } from '../../hooks/useTriageBlock';

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

const distributeSpy = vi.fn();
let mockBlock: TriageBlock | undefined;

vi.mock('../../hooks/useTriageBlock', () => ({
  useTriageBlock: () => ({ data: mockBlock }),
}));
vi.mock('../../hooks/useBucketDistribute', () => ({
  useBucketDistribute: () => distributeSpy,
}));
vi.mock('../../../library/components/LabelTile', () => ({
  LabelTile: () => <div data-testid="label-tile" />,
}));
vi.mock('../../../library/components/ArtistsPanel', () => ({
  ArtistsPanel: () => <div data-testid="artists-panel" />,
}));

import { BucketPlayerPanel } from '../BucketPlayerPanel';

function r(ui: React.ReactNode) {
  // the player's waveform reads the query cache
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MantineProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const item: BucketTrack = {
  track_id: 't1', title: 'Test Track', mix_name: null, isrc: null, bpm: 124,
  length_ms: 200000, publish_date: null, spotify_release_date: null,
  spotify_id: 'sp1', release_type: null,
  artists: [{ id: 'a-1', name: 'Artist A', role: 'artist' }], label_id: null, label_name: 'Anjunadeep',
  added_at: '2026-04-21T00:00:00Z',
};

beforeEach(() => {
  togglePlayPause.mockReset();
  distributeSpy.mockReset();
  current = null;
  mockBlock = {
    id: 'b1', style_id: 's1', style_name: 'House', name: 'W1',
    date_from: '2026-01-01', date_to: '2026-01-07', status: 'IN_PROGRESS',
    created_at: '', updated_at: '', finalized_at: null,
    buckets: [
      { id: 'bk1', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Cur', inactive: false, track_count: 1 },
      { id: 'bk2', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Techno', inactive: false, track_count: 0 },
      { id: 'disc', bucket_type: 'DISCARD', category_id: null, category_name: null, inactive: false, track_count: 0 },
      { id: 'nw', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
    ],
  };
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
    expect(screen.getByText('124 BPM')).toBeInTheDocument();
  });

  it('does not show stale label meta when the playing track is not in items', () => {
    current = {
      id: 'other', title: 'Other Track', artists: 'Z',
      duration_ms: 200000, spotify_id: 'sp2', cover_url: null,
    };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.getByText('Other Track')).toBeInTheDocument();
    expect(screen.queryByText('Anjunadeep')).not.toBeInTheDocument();
  });

  it('shows distribute buttons for staging + DISCARD (not technical) when IN_PROGRESS and playing', () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.getByText('Move current track to')).toBeInTheDocument();
    expect(screen.getByText('Techno')).toBeInTheDocument();
    expect(screen.getByText('DISCARD')).toBeInTheDocument();
    expect(screen.queryByText('NEW')).not.toBeInTheDocument();
    expect(screen.queryByText('Cur')).not.toBeInTheDocument();
  });

  it("lights the playing track's suggestions, skipping the bucket it sits in", () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    // c1 is the current bucket (not a button): it stays unlit and c2 does not move up.
    const predicted = { ...item, prediction: { keep: true, category_ids: ['c1', 'c2'] } };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[predicted]} />);
    expect(screen.getByRole('button', { name: 'Techno, weaker suggestion' })).toHaveAttribute(
      'data-variant',
      'light',
    );
    expect(screen.queryByRole('button', { name: /, suggested$/ })).not.toBeInTheDocument();
  });

  it('lights DISCARD when the model calls the playing track trash', () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    const predicted = { ...item, prediction: { keep: false, category_ids: ['c2'] } };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[predicted]} />);
    expect(screen.getByRole('button', { name: 'DISCARD, suggested' }).style.background).toBe(
      'var(--color-danger-suggest-bg)',
    );
    expect(screen.getByRole('button', { name: 'Techno, weaker suggestion' })).toBeInTheDocument();
  });

  it('hides distribute buttons when the block is FINALIZED', () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    mockBlock = { ...mockBlock!, status: 'FINALIZED' };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.queryByText('Move current track to')).not.toBeInTheDocument();
  });

  it('calls distribute with the destination bucket id on tap', async () => {
    const userEvent = (await import('@testing-library/user-event')).default;
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    await userEvent.click(screen.getByText('Techno'));
    expect(distributeSpy).toHaveBeenCalledWith('bk2', undefined);
  });

  it('near the keep threshold lights the category and DISCARD pale, and tags the tap', async () => {
    const userEvent = (await import('@testing-library/user-event')).default;
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    const predicted = { ...item, prediction: { keep: true, category_ids: ['c2'], unsure: true } };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[predicted]} />);
    expect(screen.getByRole('button', { name: 'DISCARD, weaker suggestion' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Techno, weaker suggestion' }));
    expect(distributeSpy).toHaveBeenCalledWith('bk2', 'unsure');
  });

  it('renders the LabelTile after the distribute buttons when playing', () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    const heading = screen.getByText('Move current track to');
    const labelTile = screen.getByTestId('label-tile');
    expect(
      heading.compareDocumentPosition(labelTile) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
