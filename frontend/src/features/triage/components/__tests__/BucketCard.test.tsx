import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../../../i18n';
import { BucketCard } from '../BucketCard';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(
    <MemoryRouter>
      <MantineProvider>{ui}</MantineProvider>
    </MemoryRouter>,
  );
}

const tech: TriageBucket = {
  id: 'b1',
  bucket_type: 'NEW',
  category_id: null,
  category_name: null,
  inactive: false,
  track_count: 12,
};

describe('BucketCard', () => {
  it('renders bucket badge and count', () => {
    r(<BucketCard bucket={tech} styleId="s1" blockId="bl1" />);
    expect(screen.getByText('NEW')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });
  it('links to /triage/:styleId/:blockId/buckets/:bucketId', () => {
    r(<BucketCard bucket={tech} styleId="s1" blockId="bl1" />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/triage/s1/bl1/buckets/b1');
  });
  it('dims inactive STAGING via opacity', () => {
    const inactive: TriageBucket = {
      id: 'b2',
      bucket_type: 'STAGING',
      category_id: 'c1',
      category_name: 'Old',
      inactive: true,
      track_count: 3,
    };
    r(<BucketCard bucket={inactive} styleId="s1" blockId="bl1" />);
    const link = screen.getByRole('link');
    expect(link).toHaveStyle('opacity: 0.5');
  });

  it('mode="select" renders a button and calls onSelect', async () => {
    const onSelect = vi.fn();
    const bucket = {
      id: 'b1',
      bucket_type: 'NEW' as const,
      category_id: null,
      category_name: null,
      inactive: false,
      track_count: 5,
    };
    r(
      <BucketCard
        bucket={bucket}
        styleId="s1"
        blockId="bl1"
        mode="select"
        onSelect={onSelect}
      />,
    );
    const btn = screen.getByRole('button');
    await userEvent.click(btn);
    expect(onSelect).toHaveBeenCalledWith(bucket);
  });

  it('mode="select" + inactive STAGING is disabled and does not fire onSelect', async () => {
    const onSelect = vi.fn();
    const bucket = {
      id: 'b1',
      bucket_type: 'STAGING' as const,
      category_id: 'c1',
      category_name: 'Tech',
      inactive: true,
      track_count: 0,
    };
    r(
      <BucketCard
        bucket={bucket}
        styleId="s1"
        blockId="bl1"
        mode="select"
        onSelect={onSelect}
      />,
    );
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    await userEvent.click(btn);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('mode="select" + disabled prop disables card regardless of bucket state', async () => {
    const onSelect = vi.fn();
    const bucket = {
      id: 'b1',
      bucket_type: 'NEW' as const,
      category_id: null,
      category_name: null,
      inactive: false,
      track_count: 5,
    };
    r(
      <BucketCard
        bucket={bucket}
        styleId="s1"
        blockId="bl1"
        mode="select"
        onSelect={onSelect}
        disabled
      />,
    );
    expect(screen.getByRole('button')).toBeDisabled();
  });
});
