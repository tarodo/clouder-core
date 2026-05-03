import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { TransferBlockOption } from '../TransferBlockOption';
import type { TriageBlockSummary } from '../../hooks/useTriageBlocksByStyle';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const block: TriageBlockSummary = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  track_count: 5,
};

describe('TransferBlockOption', () => {
  it('renders block name, date range, and track count (plural)', () => {
    r(<TransferBlockOption block={block} onSelect={vi.fn()} />);
    expect(screen.getByText('W17')).toBeInTheDocument();
    expect(screen.getByText(/2026-04-21 → 2026-04-28/)).toBeInTheDocument();
    expect(screen.getByText(/5 tracks/)).toBeInTheDocument();
  });

  it('renders singular track count when count is 1', () => {
    r(<TransferBlockOption block={{ ...block, track_count: 1 }} onSelect={vi.fn()} />);
    expect(screen.getByText(/1 track(?!s)/)).toBeInTheDocument();
  });

  it('calls onSelect when clicked', async () => {
    const onSelect = vi.fn();
    r(<TransferBlockOption block={block} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('calls onSelect on keyboard activation (Enter)', async () => {
    const onSelect = vi.fn();
    r(<TransferBlockOption block={block} onSelect={onSelect} />);
    const btn = screen.getByRole('button');
    btn.focus();
    await userEvent.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
