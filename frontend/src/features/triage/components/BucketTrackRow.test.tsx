import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider, Table } from '@mantine/core';
import { BucketTrackRow } from './BucketTrackRow';
import { telemetry } from '../../../lib/telemetry/sdk';
import type { BucketTrack } from '../hooks/useBucketTracks';

const track: BucketTrack = {
  track_id: 'tr-7',
  title: 'Title',
  mix_name: null,
  isrc: null,
  bpm: 120,
  length_ms: 200_000,
  publish_date: null,
  spotify_release_date: null,
  spotify_id: 'sp-7',
  release_type: null,
  artists: [{ id: 'a', name: 'Artist', role: 'main' }],
  label_id: null,
  label_name: null,
  added_at: '2026-01-01',
};

function renderRow() {
  return render(
    <MantineProvider>
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={track}
            variant="desktop"
            buckets={[]}
            currentBucketId="b1"
            onMove={() => {}}
            showMoveMenu={false}
          />
        </Table.Tbody>
      </Table>
    </MantineProvider>,
  );
}

describe('BucketTrackRow track_view', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('counts the row as seen on mount and emits track_view (track_id, not id) on unmount', () => {
    const trackSpy = vi.spyOn(telemetry, 'track');
    const seenSpy = vi.spyOn(telemetry, 'markSeen');
    const { unmount } = renderRow();
    expect(seenSpy).toHaveBeenCalledWith('tr-7');
    unmount();
    expect(trackSpy).toHaveBeenCalledWith(
      'track_view',
      expect.objectContaining({ track_id: 'tr-7' }),
    );
  });
});

describe('AI reputation badges', () => {
  const rich: BucketTrack = {
    ...track,
    artists: [{ id: 'a', name: 'Artist', role: 'main', ai: { level: 1 as const, ai: 2, checked: 41, total: 300 } }],
    label_id: 'l',
    label_name: 'Label',
    label_ai: { level: 3 as const, ai: 80, checked: 87, total: 869 },
  };
  it.each(['desktop', 'mobile'] as const)('mark the artist and the label (%s)', (variant) => {
    const row = (
      <BucketTrackRow track={rich} variant={variant} buckets={[]} currentBucketId="b1"
        onMove={() => {}} showMoveMenu={false} />
    );
    render(
      <MantineProvider>
        {variant === 'desktop' ? <Table><Table.Tbody>{row}</Table.Tbody></Table> : row}
      </MantineProvider>,
    );
    expect(screen.getByLabelText('AI level 1')).toBeInTheDocument();
    expect(screen.getByLabelText('AI level 3')).toBeInTheDocument();
  });
});
