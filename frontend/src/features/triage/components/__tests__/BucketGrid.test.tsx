import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});
