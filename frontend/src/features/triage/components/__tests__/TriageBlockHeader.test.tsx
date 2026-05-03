import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { TriageBlockHeader } from '../TriageBlockHeader';
import type { TriageBlock } from '../../hooks/useTriageBlock';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const inProgress: TriageBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [],
};

describe('TriageBlockHeader IN_PROGRESS', () => {
  it('renders title, dates, status badge, Finalize button (disabled), kebab', () => {
    r(<TriageBlockHeader block={inProgress} onDelete={() => {}} />);
    expect(screen.getByText('W17')).toBeInTheDocument();
    expect(screen.getByText('IN_PROGRESS')).toBeInTheDocument();
    expect(screen.getByText(/2026-04-21.*2026-04-28/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Finalize/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Delete block/ })).toBeInTheDocument();
  });

  it('opens kebab menu and calls onDelete', async () => {
    const onDelete = vi.fn();
    r(<TriageBlockHeader block={inProgress} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole('button', { name: /Delete block/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Delete block/ }));
    expect(onDelete).toHaveBeenCalled();
  });
});

describe('TriageBlockHeader FINALIZED', () => {
  const finalized: TriageBlock = {
    ...inProgress,
    status: 'FINALIZED',
    finalized_at: '2026-04-22T10:00:00Z',
  };

  it('shows FINALIZED badge + finalized_at, hides Finalize and kebab', () => {
    r(<TriageBlockHeader block={finalized} onDelete={() => {}} />);
    expect(screen.getByText('FINALIZED')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Finalize/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete block/ })).not.toBeInTheDocument();
    expect(screen.getByText(/^finalized\s+/)).toBeInTheDocument();
  });
});
