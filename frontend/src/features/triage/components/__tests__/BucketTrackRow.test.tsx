import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider, Table } from '@mantine/core';
import '../../../../i18n';
import { BucketTrackRow } from '../BucketTrackRow';
import type { BucketTrack } from '../../hooks/useBucketTracks';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const track: BucketTrack = {
  track_id: 't1',
  title: 'Test Track',
  mix_name: 'Original Mix',
  isrc: null,
  bpm: 124,
  length_ms: 360_000,
  publish_date: '2026-04-21',
  spotify_release_date: '2026-04-15',
  spotify_id: null,
  release_type: null,
  is_ai_suspected: false,
  artists: ['Artist A', 'Artist B'],
  added_at: '2026-04-21T08:00:00Z',
};

const buckets: TriageBucket[] = [
  { id: 'src', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 1 },
  { id: 'dst', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
];

describe('BucketTrackRow desktop', () => {
  it('renders title, mix_name, artists.join, bpm, length, release date', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={track}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.getByText('Test Track')).toBeInTheDocument();
    expect(screen.getByText('Original Mix')).toBeInTheDocument();
    expect(screen.getByText('Artist A, Artist B')).toBeInTheDocument();
    expect(screen.getByText('124')).toBeInTheDocument();
    expect(screen.getByText('6:00')).toBeInTheDocument();
    expect(screen.getByText('2026-04-15')).toBeInTheDocument();
  });

  it('shows AI warning when is_ai_suspected', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, is_ai_suspected: true }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.getByLabelText(/AI-suspected track/i)).toBeInTheDocument();
  });

  it('hides MoveToMenu when showMoveMenu=false (FINALIZED)', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={track}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu={false}
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.queryByRole('button', { name: /Move track/ })).not.toBeInTheDocument();
  });
});

describe('BucketTrackRow mobile', () => {
  it('renders fields including Beatport publish_date secondary', () => {
    r(
      <BucketTrackRow
        track={track}
        variant="mobile"
        buckets={buckets}
        currentBucketId="src"
        onMove={vi.fn()}
        showMoveMenu
      />,
    );
    expect(screen.getByText('Test Track')).toBeInTheDocument();
    expect(screen.getByText(/Beatport: 2026-04-21/)).toBeInTheDocument();
  });
});
