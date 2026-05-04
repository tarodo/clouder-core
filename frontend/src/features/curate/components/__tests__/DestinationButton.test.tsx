// frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { DestinationButton } from '../DestinationButton';
import type { TriageBucket } from '../../../triage/lib/bucketLabels';

const stage: TriageBucket = {
  id: 's1',
  bucket_type: 'STAGING',
  inactive: false,
  track_count: 0,
  category_id: 'c1',
  category_name: 'Big Room',
};

const newBucket: TriageBucket = {
  id: 'b-new',
  bucket_type: 'NEW',
  inactive: false,
  track_count: 5,
};

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('DestinationButton', () => {
  it('renders the staging bucket label and hotkey badge', () => {
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={false}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to Big Room/i })).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('renders technical bucket label', () => {
    render(
      wrap(
        <DestinationButton
          bucket={newBucket}
          hotkeyHint="Q"
          justTapped={false}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to NEW/ })).toBeInTheDocument();
  });

  it('fires onClick when clicked', () => {
    const onClick = vi.fn();
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={false}
          disabled={false}
          onClick={onClick}
        />,
      ),
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('disabled prevents clicks', () => {
    const onClick = vi.fn();
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={false}
          disabled={true}
          onClick={onClick}
        />,
      ),
    );
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('sets data-just-tapped="true" when justTapped is true', () => {
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint="1"
          justTapped={true}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button')).toHaveAttribute('data-just-tapped', 'true');
  });

  it('renders inactive staging with disabled title', () => {
    const inactive = { ...stage, inactive: true };
    render(
      wrap(
        <DestinationButton
          bucket={inactive}
          hotkeyHint="1"
          justTapped={false}
          disabled={true}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button')).toHaveAttribute(
      'title',
      expect.stringContaining('Category inactive'),
    );
  });

  it('omits hotkey badge when hotkeyHint is null', () => {
    render(
      wrap(
        <DestinationButton
          bucket={stage}
          hotkeyHint={null}
          justTapped={false}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.queryByText('1')).toBeNull();
  });
});
