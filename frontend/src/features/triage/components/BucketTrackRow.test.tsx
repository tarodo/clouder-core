import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
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
  is_ai_suspected: false,
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
