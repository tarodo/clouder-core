import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { CategoryDetailHeader } from '../CategoryDetailHeader';

function ui(props: Partial<Parameters<typeof CategoryDetailHeader>[0]> = {}) {
  return (
    <MantineProvider>
      <CategoryDetailHeader
        name="Peak Time Techno"
        trackCountLabel="42 tracks"
        onRename={vi.fn()}
        onDelete={vi.fn()}
        {...props}
      />
    </MantineProvider>
  );
}

describe('CategoryDetailHeader', () => {
  it('renders the name, track count, and both actions', () => {
    render(ui());
    expect(screen.getByRole('heading', { name: 'Peak Time Techno' })).toBeInTheDocument();
    expect(screen.getByText('42 tracks')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /rename/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument();
  });

  it('renders the actions immediately after the name (before the track count)', () => {
    render(ui());
    const heading = screen.getByRole('heading', { name: 'Peak Time Techno' });
    const rename = screen.getByRole('button', { name: /rename/i });
    const count = screen.getByText('42 tracks');
    // DOM order: name → rename → … → track count
    expect(heading.compareDocumentPosition(rename) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(rename.compareDocumentPosition(count) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('fires onRename and onDelete', async () => {
    const onRename = vi.fn();
    const onDelete = vi.fn();
    render(ui({ onRename, onDelete }));
    await userEvent.click(screen.getByRole('button', { name: /rename/i }));
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
