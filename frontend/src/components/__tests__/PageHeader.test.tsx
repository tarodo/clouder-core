import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { PageHeader } from '../PageHeader';

function renderHeader(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('PageHeader', () => {
  it('renders the title as an h2', () => {
    renderHeader(<PageHeader title="Enrichment Runs" />);
    const heading = screen.getByText('Enrichment Runs');
    expect(heading.tagName).toBe('H2');
  });

  it('renders a subtitle when provided', () => {
    renderHeader(<PageHeader title="Runs" subtitle="Queue and history of runs" />);
    expect(screen.getByText('Queue and history of runs')).toBeInTheDocument();
  });

  it('renders a back-link that fires onBack', async () => {
    const onBack = vi.fn();
    renderHeader(<PageHeader title="Artist" backLink={{ label: '← Library', onClick: onBack }} />);
    await userEvent.click(screen.getByRole('button', { name: '← Library' }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('renders actions and bottom children', () => {
    renderHeader(
      <PageHeader title="Labels" actions={<button>Add</button>}>
        <div data-testid="tabs">tabs</div>
      </PageHeader>,
    );
    expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument();
    expect(screen.getByTestId('tabs')).toBeInTheDocument();
  });
});
