import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../../../i18n';
import { BucketGrid } from '../BucketGrid';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(
    <MemoryRouter>
      <MantineProvider>{ui}</MantineProvider>
    </MemoryRouter>,
  );
}

const buckets: TriageBucket[] = [
  { id: 'b1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 5 },
  { id: 'b2', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 2 },
  { id: 'b3', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 3 },
];

describe('BucketGrid', () => {
  it('renders all buckets in given order', () => {
    r(<BucketGrid buckets={buckets} styleId="s1" blockId="bl1" />);
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute('href', '/triage/s1/bl1/buckets/b1');
    expect(links[1]).toHaveAttribute('href', '/triage/s1/bl1/buckets/b2');
    expect(links[2]).toHaveAttribute('href', '/triage/s1/bl1/buckets/b3');
  });

  it('default mode is navigate (cards wrapped in Link)', () => {
    r(<BucketGrid buckets={buckets} styleId="s1" blockId="bl1" />);
    expect(screen.getAllByRole('link')).toHaveLength(buckets.length);
  });

  it('mode="select" wraps cards in buttons and calls onSelect', async () => {
    const onSelect = vi.fn();
    r(
      <BucketGrid
        buckets={buckets}
        styleId="s1"
        blockId="bl1"
        mode="select"
        onSelect={onSelect}
      />,
    );
    const btns = screen.getAllByRole('button');
    expect(btns).toHaveLength(buckets.length);
    expect(screen.queryByRole('link')).toBeNull();

    await userEvent.click(btns[0]!);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'b1' }));
  });

  it('mode="select" disables inactive STAGING buckets', async () => {
    const onSelect = vi.fn();
    const withInactive: TriageBucket[] = [
      ...buckets,
      {
        id: 'b4',
        bucket_type: 'STAGING',
        category_id: 'c2',
        category_name: 'Old',
        inactive: true,
        track_count: 0,
      },
    ];
    r(
      <BucketGrid
        buckets={withInactive}
        styleId="s1"
        blockId="bl1"
        mode="select"
        onSelect={onSelect}
      />,
    );
    const btns = screen.getAllByRole('button');
    const inactiveBtn = btns[btns.length - 1]!;
    expect(inactiveBtn).toBeDisabled();
    await userEvent.click(inactiveBtn);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('mode="select" with disabled prop disables every card', async () => {
    const onSelect = vi.fn();
    r(
      <BucketGrid
        buckets={buckets}
        styleId="s1"
        blockId="bl1"
        mode="select"
        onSelect={onSelect}
        disabled
      />,
    );
    for (const btn of screen.getAllByRole('button')) {
      expect(btn).toBeDisabled();
    }
  });

  it('respects custom cols prop in navigate mode', () => {
    r(
      <BucketGrid
        buckets={buckets}
        styleId="s1"
        blockId="bl1"
        cols={{ base: 1, xs: 2 }}
      />,
    );
    expect(screen.getAllByRole('link')).toHaveLength(buckets.length);
  });
});
