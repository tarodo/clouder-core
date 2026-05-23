/**
 * Browser-mode layout regression for the tracks filter row.
 *
 * Requirement: the "Fresh only" switch must be vertically centered to the
 * "Manage tags" button (it previously sat on the row's bottom edge because the
 * outer filter row aligns to flex-end). Only a real browser measures layout, so
 * this assertion lives here.
 *
 * The tags barrel is stubbed so TracksTab renders without any network (its tag
 * filter bar would otherwise fetch). The pure URL helpers are kept real.
 */
import { MantineProvider } from '@mantine/core';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, test, vi } from 'vitest';
import '../../../../i18n';

vi.mock('../../../tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../tags')>();
  return {
    ...actual,
    TagsFilterBar: () => <div data-testid="tags-filter-bar" />,
    TagsManagerModal: () => null,
  };
});

import { TracksTab, type TracksTabProps } from '../TracksTab';

function props(): TracksTabProps {
  return {
    categoryId: 'c1',
    styleId: 's1',
    items: [],
    total: 0,
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    rawSearch: '',
    setRawSearch: vi.fn(),
    debounced: '',
    sortKey: 'added_at',
    sortDir: 'desc',
    setSortKey: vi.fn(),
    setSortDir: vi.fn(),
    onPlay: vi.fn(),
    currentTrackId: null,
  };
}

function mid(el: Element): number {
  const r = el.getBoundingClientRect();
  return r.top + r.height / 2;
}

describe('TracksTab filter row — layout (browser)', () => {
  test('"Fresh only" switch is vertically centered to the "Manage tags" button', () => {
    const { container, getByText } = render(
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter initialEntries={['/categories/s1/c1']}>
          <TracksTab {...props()} />
        </MemoryRouter>
      </MantineProvider>,
    );

    const manageBtn = getByText('Manage tags').closest('button')!;
    const switchRoot = container.querySelector('.mantine-Switch-root')!;
    expect(manageBtn).not.toBeNull();
    expect(switchRoot).not.toBeNull();

    // centered to each other within 2px (the bug had the switch ~7px lower)
    expect(Math.abs(mid(switchRoot) - mid(manageBtn))).toBeLessThan(2);
  });
});
