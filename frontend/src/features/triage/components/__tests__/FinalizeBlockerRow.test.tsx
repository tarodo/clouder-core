import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../../../i18n';
import { FinalizeBlockerRow } from '../FinalizeBlockerRow';

function r(ui: React.ReactNode) {
  return render(
    <MemoryRouter>
      <MantineProvider>{ui}</MantineProvider>
    </MemoryRouter>,
  );
}

describe('FinalizeBlockerRow', () => {
  it('renders category name, plural track count, and Open link with href', () => {
    r(
      <FinalizeBlockerRow
        categoryName="Tech House"
        trackCount={3}
        href="/triage/s1/b1/buckets/bk1"
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByText('Tech House')).toBeInTheDocument();
    expect(screen.getByText('3 tracks')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Open' });
    expect(link).toHaveAttribute('href', '/triage/s1/b1/buckets/bk1');
  });

  it('renders singular for trackCount=1', () => {
    r(
      <FinalizeBlockerRow
        categoryName="X"
        trackCount={1}
        href="/x"
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByText('1 track')).toBeInTheDocument();
  });

  it('calls onNavigate when Open link is clicked', async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    r(
      <FinalizeBlockerRow
        categoryName="Cat"
        trackCount={1}
        href="/triage/s1/b1/buckets/bk1"
        onNavigate={onNavigate}
      />,
    );
    await user.click(screen.getByRole('link', { name: 'Open' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});
