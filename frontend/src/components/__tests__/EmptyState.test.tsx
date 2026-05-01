import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { EmptyState } from '../EmptyState';

function wrap(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('EmptyState', () => {
  it('renders title + body', () => {
    wrap(<EmptyState title="Coming soon" body="Wait." />);
    expect(screen.getByText('Coming soon')).toBeInTheDocument();
    expect(screen.getByText('Wait.')).toBeInTheDocument();
  });

  it('fires onClick from action button', async () => {
    let clicked = false;
    wrap(
      <EmptyState
        title="t"
        action={{
          label: 'go',
          onClick: () => {
            clicked = true;
          },
        }}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'go' }));
    expect(clicked).toBe(true);
  });
});
