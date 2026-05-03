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

function block(overrides: Partial<TriageBlock> = {}): TriageBlock {
  return {
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
    ...overrides,
  };
}

const inProgress: TriageBlock = block();

describe('TriageBlockHeader IN_PROGRESS', () => {
  it('renders title, dates, status badge, Finalize button, kebab', () => {
    r(<TriageBlockHeader block={inProgress} onDelete={() => {}} onFinalize={() => {}} />);
    expect(screen.getByText('W17')).toBeInTheDocument();
    expect(screen.getByText('IN_PROGRESS')).toBeInTheDocument();
    expect(screen.getByText(/2026-04-21.*2026-04-28/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Finalize/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Delete block/ })).toBeInTheDocument();
  });

  it('opens kebab menu and calls onDelete', async () => {
    const onDelete = vi.fn();
    r(<TriageBlockHeader block={inProgress} onDelete={onDelete} onFinalize={() => {}} />);
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
    r(<TriageBlockHeader block={finalized} onDelete={() => {}} onFinalize={() => {}} />);
    expect(screen.getByText('FINALIZED')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Finalize/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete block/ })).not.toBeInTheDocument();
    expect(screen.getByText(/^finalized\s+/)).toBeInTheDocument();
  });
});

describe('TriageBlockHeader Finalize CTA', () => {
  it('renders enabled Finalize button when status=IN_PROGRESS and calls onFinalize on click', async () => {
    const onFinalize = vi.fn();
    const user = userEvent.setup();
    r(<TriageBlockHeader block={block()} onDelete={() => {}} onFinalize={onFinalize} />);
    const btn = screen.getByRole('button', { name: 'Finalize' });
    expect(btn).toBeEnabled();
    await user.click(btn);
    expect(onFinalize).toHaveBeenCalledTimes(1);
  });

  it('does not render Finalize button when status=FINALIZED', () => {
    r(
      <TriageBlockHeader
        block={block({ status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' })}
        onDelete={() => {}}
        onFinalize={() => {}}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Finalize' })).not.toBeInTheDocument();
  });
});
