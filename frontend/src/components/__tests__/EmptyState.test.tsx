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

  it('inline variant uses an h3 heading (not the page-level h2)', () => {
    wrap(<EmptyState title="Empty list" variant="inline" />);
    const heading = screen.getByText('Empty list');
    expect(heading.tagName).toBe('H3');
  });

  it('page variant keeps the h2 heading', () => {
    wrap(<EmptyState title="Not found" variant="page" />);
    expect(screen.getByText('Not found').tagName).toBe('H2');
  });
});
