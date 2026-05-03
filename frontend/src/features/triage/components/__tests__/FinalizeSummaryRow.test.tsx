import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { FinalizeSummaryRow } from '../FinalizeSummaryRow';
import type { TriageBucket } from '../../lib/bucketLabels';

const mkBucket = (overrides: Partial<TriageBucket> = {}): TriageBucket => ({
  id: 'bk1',
  bucket_type: 'STAGING',
  category_id: 'cat1',
  category_name: 'Tech House',
  inactive: false,
  track_count: 7,
  ...overrides,
});

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('FinalizeSummaryRow', () => {
  it('renders category name and plural count', () => {
    r(<FinalizeSummaryRow bucket={mkBucket({ track_count: 7 })} />);
    expect(screen.getByText('Tech House')).toBeInTheDocument();
    expect(screen.getByText('+7 tracks')).toBeInTheDocument();
  });

  it('renders singular count when track_count = 1', () => {
    r(<FinalizeSummaryRow bucket={mkBucket({ track_count: 1 })} />);
    expect(screen.getByText('+1 track')).toBeInTheDocument();
  });

  it('renders dash when category_name is null', () => {
    r(<FinalizeSummaryRow bucket={mkBucket({ category_name: null })} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
