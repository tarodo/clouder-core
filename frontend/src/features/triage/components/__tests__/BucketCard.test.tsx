import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});
