import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  artists: [{ id: 'a-1', name: 'Artist A', role: 'artist' }, { id: 'a-2', name: 'Artist B', role: 'artist' }],
  label_id: null,
  label_name: 'Anjunadeep',
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

  it('passes onTransfer through to MoveToMenu when blockStatus=IN_PROGRESS', async () => {
    const onTransfer = vi.fn();
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{
              track_id: 'tk1', title: 't', mix_name: null, isrc: null, bpm: null,
              length_ms: null, publish_date: null, spotify_release_date: null,
              spotify_id: null, release_type: null, is_ai_suspected: false,
              artists: [{ id: 'a-1', name: 'a', role: 'artist' }], label_id: null, label_name: null, added_at: '2026-04-21T00:00:00Z',
            }}
            variant="desktop"
            buckets={[
              { id: 'cur', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 1 },
            ]}
            currentBucketId="cur"
            onMove={vi.fn()}
            onTransfer={onTransfer}
            showMoveMenu
            blockStatus="IN_PROGRESS"
          />
        </Table.Tbody>
      </Table>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    expect(onTransfer).toHaveBeenCalledTimes(1);
  });

  it('renders an enabled Play button and calls onPlay when track has spotify_id', async () => {
    const onPlay = vi.fn();
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, spotify_id: 'sp1' }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
            onPlay={onPlay}
          />
        </Table.Tbody>
      </Table>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Play track/i }));
    expect(onPlay).toHaveBeenCalledTimes(1);
  });

  it('disables the Play button when spotify_id is null', () => {
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
            onPlay={vi.fn()}
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.getByRole('button', { name: /no spotify track available/i })).toBeDisabled();
  });

  it('marks the row data-current when isCurrent', () => {
    const { container } = r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, spotify_id: 'sp1' }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
            onPlay={vi.fn()}
            isCurrent
          />
        </Table.Tbody>
      </Table>,
    );
    expect(container.querySelector('[data-current="true"]')).not.toBeNull();
  });

  it('renders no Play button when onPlay is omitted', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, spotify_id: 'sp1' }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.queryByRole('button', { name: /Play track/i })).not.toBeInTheDocument();
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
