import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { BucketDistributeButtons } from '../BucketDistributeButtons';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const staging: TriageBucket = {
  id: 'bk2', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Techno',
  inactive: false, track_count: 0,
};
const discard: TriageBucket = {
  id: 'disc', bucket_type: 'DISCARD', category_id: null, category_name: null,
  inactive: false, track_count: 0,
};

describe('BucketDistributeButtons', () => {
  it('renders a button per destination with bucket labels', () => {
    r(<BucketDistributeButtons destinations={[staging, discard]} onDistribute={vi.fn()} />);
    expect(screen.getByText('Move current track to')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Techno' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'DISCARD' })).toBeInTheDocument();
  });

  it('calls onDistribute with the bucket id on click', async () => {
    const onDistribute = vi.fn();
    r(<BucketDistributeButtons destinations={[staging, discard]} onDistribute={onDistribute} />);
    await userEvent.click(screen.getByRole('button', { name: 'Techno' }));
    expect(onDistribute).toHaveBeenCalledWith('bk2');
  });

  it('renders nothing when there are no destinations', () => {
    r(<BucketDistributeButtons destinations={[]} onDistribute={vi.fn()} />);
    // MantineProvider injects <style> tags so we cannot assert toBeEmptyDOMElement;
    // instead verify no buttons or heading are rendered.
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByTestId('bucket-distribute')).toBeNull();
  });
});
