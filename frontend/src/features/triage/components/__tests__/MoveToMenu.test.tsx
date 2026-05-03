import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { MoveToMenu } from '../MoveToMenu';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const buckets: TriageBucket[] = [
  { id: 'src', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 2 },
  { id: 'dst', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
  { id: 'staging', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 0 },
  { id: 'staging-inactive', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Old', inactive: true, track_count: 0 },
];

describe('MoveToMenu', () => {
  it('lists active destinations excluding current and inactive STAGING', async () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} />);
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    expect(await screen.findByRole('menuitem', { name: /Move to OLD/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Move to Tech \(staging\)/ })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /Move to NEW/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('menuitem', { name: /Old \(staging, inactive\)/ }),
    ).not.toBeInTheDocument();
  });

  it('calls onMove with the destination bucket', async () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} />);
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ id: 'dst' }));
  });

  it('renders disabled trigger when destinations empty', () => {
    const onMove = vi.fn();
    const onlyCurrent: TriageBucket[] = [buckets[0]!];
    r(<MoveToMenu buckets={onlyCurrent} currentBucketId="src" onMove={onMove} />);
    expect(screen.getByRole('button', { name: /Move track/ })).toBeDisabled();
  });

  it('renders disabled trigger when disabled prop set', () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} disabled />);
    expect(screen.getByRole('button', { name: /Move track/ })).toBeDisabled();
  });

  it('shows Transfer item after divider when showTransfer + onTransfer provided', async () => {
    const onMove = vi.fn();
    const onTransfer = vi.fn();
    r(
      <MoveToMenu
        buckets={buckets}
        currentBucketId="src"
        onMove={onMove}
        showTransfer
        onTransfer={onTransfer}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    expect(
      await screen.findByRole('menuitem', { name: /Transfer to other block/ }),
    ).toBeInTheDocument();
  });

  it('hides Transfer item when showTransfer is false', async () => {
    const onMove = vi.fn();
    const onTransfer = vi.fn();
    r(
      <MoveToMenu
        buckets={buckets}
        currentBucketId="src"
        onMove={onMove}
        showTransfer={false}
        onTransfer={onTransfer}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await screen.findByRole('menuitem', { name: /Move to OLD/ });
    expect(
      screen.queryByRole('menuitem', { name: /Transfer to other block/ }),
    ).not.toBeInTheDocument();
  });

  it('hides Transfer item when onTransfer is omitted', async () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} showTransfer />);
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await screen.findByRole('menuitem', { name: /Move to OLD/ });
    expect(
      screen.queryByRole('menuitem', { name: /Transfer to other block/ }),
    ).not.toBeInTheDocument();
  });

  it('clicking Transfer fires onTransfer callback', async () => {
    const onMove = vi.fn();
    const onTransfer = vi.fn();
    r(
      <MoveToMenu
        buckets={buckets}
        currentBucketId="src"
        onMove={onMove}
        showTransfer
        onTransfer={onTransfer}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /Transfer to other block/ }),
    );
    expect(onTransfer).toHaveBeenCalledTimes(1);
  });

  it('with empty destinations + showTransfer, trigger is enabled and Transfer is the only item', async () => {
    const onMove = vi.fn();
    const onTransfer = vi.fn();
    const onlyCurrent: TriageBucket[] = [buckets[0]!];
    r(
      <MoveToMenu
        buckets={onlyCurrent}
        currentBucketId="src"
        onMove={onMove}
        showTransfer
        onTransfer={onTransfer}
      />,
    );
    const trigger = screen.getByRole('button', { name: /Move track/ });
    expect(trigger).not.toBeDisabled();
    await userEvent.click(trigger);
    const items = await screen.findAllByRole('menuitem');
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveAccessibleName(/Transfer to other block/);
  });
});
