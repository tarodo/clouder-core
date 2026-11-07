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
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, test, vi } from 'vitest';
import { page } from 'vitest/browser';
import '../../../../i18n';

vi.mock('../../tags', () => ({
  TrackTagsCell: ({ tags }: { tags: { id: string; name: string }[] }) => (
    <span>{tags.map((t) => t.name).join(' ')}</span>
  ),
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
  used_in_playlist: false,
  added_at: '2026-05-12T00:00:00Z',
  source_triage_block_id: null,
  tags: [],
};

describe('TrackRow — browser smoke', () => {
  test('active, playing row shows the Pause control', () => {
    const { getByRole } = render(
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
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
        </MemoryRouter>
      </MantineProvider>,
    );

    const pause = getByRole('button', { name: /pause track/i });
    expect(pause).toBeVisible();
    expect(pause.getBoundingClientRect().width).toBeGreaterThan(0);
  });

  test('a long label ends in an ellipsis, its AI badge stays in the cell', () => {
    const rep = { level: 3, ai: 9, checked: 10, total: 12 } as const;
    render(
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <Table style={{ width: 640 }}>
            <Table.Tbody>
              <TrackRow
                track={{
                  ...track,
                  artists: [{ id: 'a1', name: 'An Artist With A Very Long Name Indeed', ai: rep }],
                  label: { id: 'l1', name: 'A Label Whose Name Is Far Too Long For Its Column', ai: rep },
                }}
                variant="desktop"
              />
            </Table.Tbody>
          </Table>
        </MemoryRouter>
      </MantineProvider>,
    );
    for (const name of [/^An Artist/, /^A Label/]) {
      const text = screen.getByText(name);
      const cell = text.closest('td')!.getBoundingClientRect();
      const badge = text.closest('td')!.querySelector('[data-level]')!.getBoundingClientRect();
      expect(badge.width).toBeGreaterThan(0);
      expect(badge.right).toBeLessThanOrEqual(cell.right);
      // the name, not the badge, gave up the room
      const box = text.closest('[data-name]')!;
      expect(box.scrollWidth).toBeGreaterThan(box.clientWidth);
    }
  });

  test('phone: the label AI badge stays on a line that ends in an ellipsis', async () => {
    await page.viewport(390, 844);
    render(
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <div style={{ width: 358 }}>
            <TrackRow
              track={{
                ...track,
                artists: [{ id: 'a1', name: 'An Artist With A Very Long Name Indeed' }],
                label: {
                  id: 'l1',
                  name: 'A Label Whose Name Is Far Too Long',
                  ai: { level: 2, ai: 3, checked: 10, total: 12 },
                },
              }}
              variant="mobile"
            />
          </div>
        </MemoryRouter>
      </MantineProvider>,
    );
    const card = screen.getByText(/^An Artist/).closest('.mantine-Card-root')!.getBoundingClientRect();
    const badge = screen.getByLabelText('AI level 2').getBoundingClientRect();
    expect(badge.width).toBeGreaterThan(0);
    expect(badge.right).toBeLessThanOrEqual(card.right);
  });

  test('phone: a card is three lines — title + mix, artists + label, BPM/key/date + tags', async () => {
    await page.viewport(390, 844);
    render(
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <div style={{ width: 358 }}>
            <TrackRow
              track={{
                ...track,
                key_camelot: '8A',
                tags: [{ id: 'g', name: 'Groovy', color: null }],
              }}
              variant="mobile"
              onPlay={vi.fn()}
              // the row menu's ActionIcon is 28px
              actions={
                <button
                  type="button"
                  aria-label="Track actions"
                  style={{ width: 28, height: 28 }}
                />
              }
            />
          </div>
        </MemoryRouter>
      </MantineProvider>,
    );
    const box = (text: string | RegExp) => screen.getByText(text).getBoundingClientRect();
    const card = screen.getByText('Deep Horizon').closest('.mantine-Card-root')!;
    expect(Math.abs(box('Original Mix').bottom - box('Deep Horizon').bottom)).toBeLessThan(4);
    expect(Math.abs(box('Ostgut Ton').top - box('Ben Klock').top)).toBeLessThan(4);
    expect(Math.abs(box('8A').top - box('140 BPM').top)).toBeLessThan(6);
    expect(Math.abs(box('Groovy').top - box('140 BPM').top)).toBeLessThan(6);
    // the actions sit at the title's end, not over it
    const actions = screen.getByRole('button', { name: 'Track actions' }).getBoundingClientRect();
    expect(actions.left).toBeGreaterThanOrEqual(box('Deep Horizon').right);
    expect(card.getBoundingClientRect().height).toBeLessThan(100);
    expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth);
  });
});
