/**
 * Browser-mode smoke for the category track row: in a real browser (styles
 * applied), the active + playing row shows the Pause control instead of Play,
 * so the current track is distinguishable beyond the row highlight. jsdom
 * applies no stylesheets, so this confirms the swap renders + lays out in a
 * real engine (see gotcha #11).
 *
 * The tags barrel is stubbed so the row renders without React Query / network.
 */
import { MantineProvider, Table } from '@mantine/core';
import { render } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import '../../../../i18n';

vi.mock('../../tags', () => ({
  TrackTagsCell: () => null,
}));

import { TrackRow } from '../TrackRow';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';

const track: CategoryTrack = {
  id: 't1',
  title: 'Deep Horizon',
  mix_name: 'Original Mix',
  artists: [{ id: 'a1', name: 'Ben Klock' }],
  label: { id: 'l1', name: 'Ostgut Ton' },
  bpm: 140,
  length_ms: 390_000,
  publish_date: null,
  spotify_release_date: '2024-03-15',
  isrc: null,
  spotify_id: 'sp1',
  release_type: null,
  is_ai_suspected: false,
  used_in_playlist: false,
  added_at: '2026-05-12T00:00:00Z',
  source_triage_block_id: null,
  tags: [],
};

describe('TrackRow — browser smoke', () => {
  test('active, playing row shows the Pause control', () => {
    const { getByRole } = render(
      <MantineProvider defaultColorScheme="light">
        <Table>
          <Table.Tbody>
            <TrackRow
              track={track}
              variant="desktop"
              onPlay={vi.fn()}
              onToggle={vi.fn()}
              isCurrent
              isPlaying
            />
          </Table.Tbody>
        </Table>
      </MantineProvider>,
    );

    const pause = getByRole('button', { name: /pause track/i });
    expect(pause).toBeVisible();
    expect(pause.getBoundingClientRect().width).toBeGreaterThan(0);
  });
});
