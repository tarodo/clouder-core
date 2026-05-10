// frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
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
  <I18nextProvider i18n={i18n}>
    <MantineProvider theme={testTheme}>{ui}</MantineProvider>
  </I18nextProvider>
);

describe('DestinationGrid', () => {
  it('renders DISCARD on top + staging + system sections (per P-22/P-23 design)', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    expect(screen.getByText('Staging')).toBeInTheDocument();
    expect(screen.getByText('System')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Assign to DISCARD/ })).toBeInTheDocument();
  });

  it('renders staging buttons with digit hotkeys 1-N', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to Big Room/i })).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders Q/W/E and Z hotkey badges', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    expect(screen.getByText('Q')).toBeInTheDocument();
    expect(screen.getByText('W')).toBeInTheDocument();
    expect(screen.getByText('E')).toBeInTheDocument();
    expect(screen.getByText('Z')).toBeInTheDocument();
  });

  it('passes lastTappedBucketId through to the matching DestinationButton', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId="s2"
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    const btn = screen.getByRole('button', { name: /Assign to Hard Techno/i });
    expect(btn).toHaveAttribute('data-just-tapped', 'true');
  });

  it('renders the source-bucket button as disabled (still visible so user knows it exists)', () => {
    // currentBucketId matching a tech bucket should render it as disabled
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-new"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    const newBtn = screen.getByRole('button', { name: /Assign to NEW/ });
    expect(newBtn).toBeDisabled();
  });

  it('clicking a button calls onAssign with the bucket id', () => {
    const onAssign = vi.fn();
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={onAssign}
          onToggleForce={vi.fn()}
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
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /More categories/i })).toBeInTheDocument();
  });

  it('renders ForceToggle next to DISCARD in the same flex row', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    const discardBtn = screen.getByRole('button', { name: /Assign to DISCARD/ });
    const forceBtn = screen.getByRole('button', { name: /Force mode (on|off)/ });
    // The DISCARD button is wrapped in a flex:1 div; both that wrapper and
    // the ForceToggle button share the same Group container.
    expect(discardBtn.parentElement?.parentElement).toBe(forceBtn.parentElement);
  });

  it('passes forceMode to ForceToggle (aria-pressed reflects it)', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          forceMode={true}
          onAssign={() => {}}
          onToggleForce={vi.fn()}
        />,
      ),
    );
    const forceBtn = screen.getByRole('button', { name: /Force mode (on|off)/ });
    expect(forceBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('calls onToggleForce when ForceToggle is clicked', () => {
    const onToggleForce = vi.fn();
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={() => {}}
          onToggleForce={onToggleForce}
        />,
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: /Force mode (on|off)/ }));
    expect(onToggleForce).toHaveBeenCalledTimes(1);
  });
});
