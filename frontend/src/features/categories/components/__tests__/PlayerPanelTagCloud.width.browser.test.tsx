/**
 * Browser-mode regression: selecting a tag must NOT change the chip's width.
 *
 * Mantine's Chip label switches `padding-inline` from --chip-padding (20px)
 * to --chip-checked-padding (10px) when checked. With the check icon hidden,
 * that made a selected chip ~20px narrower. PlayerPanelTagCloud now pins the
 * inline padding in both states. This test renders the SAME tag unchecked then
 * checked and asserts its label width is unchanged.
 */
import type { ReactNode } from 'react';
import { MantineProvider } from '@mantine/core';
import { render } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import '../../../../i18n';

vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [{ id: 'tg-a', name: 'acid', color: '#ff0000' }],
    isLoading: false,
  }),
  TrackTagsPopover: ({ target }: { target: ReactNode }) => <div>{target}</div>,
}));

import { PlayerPanelTagCloud } from '../PlayerPanelTagCloud';

const base = { categoryId: 'c1', trackId: 't-1', onAdd: vi.fn(), onRemove: vi.fn() };

function acidLabelWidth(container: HTMLElement): number {
  const label = container.querySelector('.mantine-Chip-label') as HTMLElement | null;
  if (!label) throw new Error('mantine-Chip-label not found');
  return label.getBoundingClientRect().width;
}

describe('PlayerPanelTagCloud — chip width stable on select (browser)', () => {
  test('the same tag has equal label width unchecked and checked', () => {
    const { container, rerender } = render(
      <MantineProvider defaultColorScheme="light">
        <PlayerPanelTagCloud {...base} assignedTagIds={[]} />
      </MantineProvider>,
    );
    const unchecked = acidLabelWidth(container);

    rerender(
      <MantineProvider defaultColorScheme="light">
        <PlayerPanelTagCloud {...base} assignedTagIds={['tg-a']} />
      </MantineProvider>,
    );
    const checked = acidLabelWidth(container);

    expect(unchecked).toBeGreaterThan(0);
    // the bug was a ~20px shrink; assert the two widths differ by < 1px
    expect(Math.abs(checked - unchecked)).toBeLessThan(1);
  });
});
