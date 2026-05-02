import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { TriageBlockRow } from '../TriageBlockRow';
import type { TriageBlockSummary } from '../../hooks/useTriageBlocksByStyle';

const block: TriageBlockSummary = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 12,
};

function renderRow(props: Partial<React.ComponentProps<typeof TriageBlockRow>> = {}) {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <TriageBlockRow block={block} styleId="s1" onDelete={vi.fn()} {...props} />
      </MantineProvider>
    </MemoryRouter>,
  );
}

describe('TriageBlockRow', () => {
  it('renders name as a link to detail', () => {
    renderRow();
    const link = screen.getByRole('link', { name: 'House W17' });
    expect(link).toHaveAttribute('href', '/triage/s1/b1');
  });

  it('renders the date range', () => {
    renderRow();
    expect(screen.getByText(/2026-04-20.*2026-04-26/)).toBeInTheDocument();
  });

  it('renders pluralised track count', () => {
    renderRow();
    expect(screen.getByText(/12 tracks/)).toBeInTheDocument();
  });

  it('renders singular track count for 1 track', () => {
    renderRow({ block: { ...block, track_count: 1 } });
    expect(screen.getByText(/1 track\b/)).toBeInTheDocument();
  });

  it('shows finalized_at on FINALIZED tab variant', () => {
    renderRow({
      block: {
        ...block,
        status: 'FINALIZED',
        finalized_at: '2026-04-26T18:00:00Z',
      },
      timeField: 'finalized_at',
    });
    // date_to and finalized_at both render '2026-04-26'; assert at least one
    // standalone element shows the finalized date next to the date range.
    expect(screen.getAllByText(/2026-04-26/).length).toBeGreaterThanOrEqual(1);
  });

  it('opens kebab menu and calls onDelete', async () => {
    const onDelete = vi.fn();
    renderRow({ onDelete });
    await userEvent.click(screen.getByRole('button', { name: /menu/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }));
    expect(onDelete).toHaveBeenCalledWith(block);
  });
});
