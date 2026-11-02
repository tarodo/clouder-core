/**
 * Browser-mode smoke for the playlist track tile: in a real browser, the tile
 * shows the play button, the position number, and the Remove button. Geometry
 * is not load-bearing here (the structure is covered by the jsdom test) — this
 * is a presence smoke that the tile renders + lays out in a real engine.
 *
 * The tags barrel is stubbed so the tile renders without React Query / network
 * (the tag popover's useTags would otherwise fetch).
 */
import type { ReactNode } from 'react';
import { MantineProvider } from '@mantine/core';
import { DndContext } from '@dnd-kit/core';
import { SortableContext } from '@dnd-kit/sortable';
import { render } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';

vi.mock('../../../tags', () => ({
  TrackTagsPopover: ({ target }: { target: ReactNode }) => <>{target}</>,
  TagPill: ({ name }: { name: string }) => <span>{name}</span>,
}));

import { PlaylistTrackRow } from '../PlaylistTrackRow';
import type { PlaylistTrack } from '../../lib/playlistTypes';

const track: PlaylistTrack = {
  track_id: 'tr-1',
  position: 0,
  added_at: '2026-05-12T00:00:00Z',
  title: 'Deep Horizon',
  spotify_id: 'sp1',
  isrc: null,
  length_ms: 390_000,
  origin: 'beatport',
  mix_name: 'Original Mix',
  artists: [{ id: 'a1', name: 'Ben Klock' }],
  label: { id: 'l1', name: 'Ostgut Ton' },
  bpm: 140,
  spotify_release_date: '2024-03-15',
  tags: [{ id: 'tg1', name: 'Dark', color: '#333' }],
};

describe('PlaylistTrackRow — browser smoke', () => {
  test('shows play, position number, and Remove in a real browser', async () => {
    await page.viewport(1280, 900);
    const { getByRole, getByText } = render(
      <MantineProvider defaultColorScheme="light">
        <DndContext>
          <SortableContext items={['tr-1']}>
            <PlaylistTrackRow
              track={track}
              position={1}
              onRemove={vi.fn()}
              onPlay={vi.fn()}
              playlistId="pl1"
            />
          </SortableContext>
        </DndContext>
      </MantineProvider>,
    );

    const play = getByRole('button', { name: /play track/i });
    const remove = getByRole('button', { name: /remove/i });
    expect(getByText('1.')).toBeVisible();
    expect(play).toBeVisible();
    expect(play.getBoundingClientRect().width).toBeGreaterThan(0);
    expect(remove).toBeVisible();
  });
});

describe('PlaylistTrackRow — phone', () => {
  test('title, artists and tags take the row; links hide behind the menu', async () => {
    await page.viewport(390, 844);
    const long: PlaylistTrack = {
      ...track,
      title: 'Purple Desert Fragments Of A Long Night',
      mix_name: 'THEOPI Remix',
      artists: [
        { id: 'a1', name: 'Ben Klock' },
        { id: 'a2', name: 'Blawan' },
        { id: 'a3', name: 'Paula Temple' },
      ],
      tags: ['5', 'p2', 'p5', 'U'].map((name, i) => ({ id: `tg${i}`, name, color: null })),
      beatport_track_id: '1',
      ytmusic: { status: 'matched', url: 'https://music.youtube.com/watch?v=x' },
    };
    const { container, findByRole, getByText, queryByRole } = render(
      <MantineProvider defaultColorScheme="light">
        <DndContext>
          <SortableContext items={['tr-1']}>
            <div style={{ width: 358 }}>
              <PlaylistTrackRow
                track={long}
                position={16}
                onRemove={vi.fn()}
                onPlay={vi.fn()}
                playlistId="pl1"
              />
            </div>
          </SortableContext>
        </DndContext>
      </MantineProvider>,
    );

    await findByRole('button', { name: /track actions/i });
    expect(queryByRole('link')).toBeNull();
    const row = container.querySelector('[style*="width: 358px"] > div') as HTMLElement;
    expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth);
    // the title column gets most of the row, not a sliver
    const title = getByText('Purple Desert Fragments Of A Long Night').parentElement as HTMLElement;
    expect(title.getBoundingClientRect().width).toBeGreaterThan(180);
    expect(getByText('Ben Klock, Blawan, Paula Temple')).toBeVisible();
    expect(getByText('U')).toBeVisible();
    await page.viewport(1280, 900);
  });
});
