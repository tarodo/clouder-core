import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { BucketBadge } from '../BucketBadge';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const tech: TriageBucket = {
  id: 'b1',
  bucket_type: 'NEW',
  category_id: null,
  category_name: null,
  inactive: false,
  track_count: 5,
};

const staging: TriageBucket = {
  id: 'b2',
  bucket_type: 'STAGING',
  category_id: 'c1',
  category_name: 'Tech House',
  inactive: false,
  track_count: 3,
};

describe('BucketBadge', () => {
  it('renders technical bucket type literal', () => {
    r(<BucketBadge bucket={tech} />);
    expect(screen.getByText('NEW')).toBeInTheDocument();
  });
  it('renders STAGING with category name', () => {
    r(<BucketBadge bucket={staging} />);
    expect(screen.getByText(/Tech House.*staging/)).toBeInTheDocument();
  });
  it('renders inactive STAGING with inactive label', () => {
    r(<BucketBadge bucket={{ ...staging, inactive: true }} />);
    expect(screen.getByText(/Tech House.*staging.*inactive/)).toBeInTheDocument();
  });
});
