// frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { DestinationGrid } from '../DestinationGrid';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

const stage = (id: string, name: string, inactive = false): TriageBucket => ({
  id,
  bucket_type: 'STAGING',
  inactive,
  track_count: 0,
  category_id: `c-${id}`,
  category_name: name,
});

const tech = (id: string, t: 'NEW' | 'OLD' | 'NOT' | 'DISCARD'): TriageBucket => ({
  id,
  bucket_type: t,
  inactive: false,
  track_count: 0,
});

const buckets: TriageBucket[] = [
  tech('b-new', 'NEW'),
  tech('b-old', 'OLD'),
  tech('b-not', 'NOT'),
  tech('b-disc', 'DISCARD'),
  stage('s1', 'Big Room'),
  stage('s2', 'Hard Techno'),
  stage('s3', 'Tech House'),
];

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('DestinationGrid', () => {
  it('renders staging / technical / discard sections', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByText('Staging')).toBeInTheDocument();
    expect(screen.getByText('Technical')).toBeInTheDocument();
    expect(screen.getByText('Discard')).toBeInTheDocument();
  });

  it('renders staging buttons with digit hotkeys 1-N', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to Big Room/i })).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders Q/W/E and 0 hotkey badges', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByText('Q')).toBeInTheDocument();
    expect(screen.getByText('W')).toBeInTheDocument();
    expect(screen.getByText('E')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('passes lastTappedBucketId through to the matching DestinationButton', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId="s2"
          onAssign={() => {}}
        />,
      ),
    );
    const btn = screen.getByRole('button', { name: /Assign to Hard Techno/i });
    expect(btn).toHaveAttribute('data-just-tapped', 'true');
  });

  it('disables the source-bucket button (excluded entirely from rendering by default)', () => {
    // currentBucketId matching a tech bucket should hide it
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-new"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.queryByRole('button', { name: /Assign to NEW/ })).toBeNull();
  });

  it('clicking a button calls onAssign with the bucket id', () => {
    const onAssign = vi.fn();
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={onAssign}
        />,
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: /Assign to Big Room/i }));
    expect(onAssign).toHaveBeenCalledWith('s1');
  });

  it('renders More… menu when staging count exceeds 9', () => {
    const many: TriageBucket[] = [
      ...buckets,
      ...Array.from({ length: 8 }, (_, i) => stage(`s-extra-${i}`, `Extra ${i}`)),
    ];
    render(
      wrap(
        <DestinationGrid
          buckets={many}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /More categories/i })).toBeInTheDocument();
  });
});
