// frontend/src/features/curate/components/__tests__/EndOfQueue.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { EndOfQueue } from '../EndOfQueue';
import type { TriageBlock } from '../../../triage/hooks/useTriageBlock';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

const pauseMock = vi.fn(async () => {});

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' as const },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    controls: {
      play: vi.fn(async () => {}),
      pause: pauseMock,
      togglePlayPause: vi.fn(async () => {}),
      next: vi.fn(async () => {}),
      prev: vi.fn(async () => {}),
      seekMs: vi.fn(async () => {}),
      seekPct: vi.fn(async () => {}),
      bindQueue: vi.fn(),
      clearQueue: vi.fn(),
      cancelPendingAdvance: vi.fn(),
      openSpotifyExternal: vi.fn(),
    },
  }),
}));

function mkBlock(buckets: TriageBucket[]): TriageBlock {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'Tech House',
    name: 'TH W17',
    date_from: '2026-04-21',
    date_to: '2026-04-27',
    status: 'IN_PROGRESS',
    created_at: '2026-04-20T00:00:00Z',
    updated_at: '2026-04-20T00:00:00Z',
    finalized_at: null,
    buckets,
  };
}

const wrap = (ui: React.ReactElement) => (
  <MemoryRouter>
    <MantineProvider theme={testTheme}>{ui}</MantineProvider>
  </MemoryRouter>
);

describe('EndOfQueue', () => {
  it('renders Bucket finished + tracks_done copy', () => {
    pauseMock.mockClear();
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
      { id: 'old', bucket_type: 'OLD', inactive: false, track_count: 5 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={5}
        />,
      ),
    );
    expect(screen.getByText(/Bucket finished/i)).toBeInTheDocument();
    expect(screen.getByText(/5 tracks done/i)).toBeInTheDocument();
  });

  it('calls playback.controls.pause on mount', () => {
    pauseMock.mockClear();
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={3}
        />,
      ),
    );
    expect(pauseMock).toHaveBeenCalled();
  });

  it('renders Continue CTA when a non-empty source-eligible bucket exists', () => {
    pauseMock.mockClear();
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
      { id: 'old', bucket_type: 'OLD', inactive: false, track_count: 5 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={3}
        />,
      ),
    );
    expect(screen.getByText(/3 tracks done/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Continue with OLD \(5\)/i })).toHaveAttribute(
      'href',
      '/curate/s1/b1/old',
    );
  });

  it('renders Finalize CTA when no non-empty source-eligible bucket exists', () => {
    pauseMock.mockClear();
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={0}
        />,
      ),
    );
    expect(screen.getByRole('link', { name: /Finalize block/i })).toHaveAttribute(
      'href',
      '/triage/s1/b1',
    );
    expect(screen.getByText(/0 tracks done/i)).toBeInTheDocument();
  });

  it('always renders Back to triage', () => {
    pauseMock.mockClear();
    const block = mkBlock([
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 0 },
    ]);
    render(
      wrap(
        <EndOfQueue
          styleId="s1"
          block={block}
          currentBucketId="src"
          totalAssigned={1}
        />,
      ),
    );
    expect(screen.getByRole('link', { name: /Back to triage/i })).toHaveAttribute(
      'href',
      '/triage/s1/b1',
    );
    expect(screen.getByText(/1 tracks done/i)).toBeInTheDocument();
  });
});
