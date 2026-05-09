import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { ActiveBlocksList } from '../ActiveBlocksList';
import type { TriageBlockSummary } from '../../../triage/hooks/useTriageBlocksByStyle';

function wrap(node: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>{node}</MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

function block(id: string, styleName: string, dateFrom: string, count: number): TriageBlockSummary {
  return {
    id, style_id: 's1', style_name: styleName, name: id,
    date_from: dateFrom, date_to: dateFrom, status: 'IN_PROGRESS',
    created_at: '2026-05-04T00:00:00Z', updated_at: '2026-05-08T00:00:00Z',
    finalized_at: null, track_count: count,
  };
}

describe('ActiveBlocksList', () => {
  it('renders one row per block with track count and link', () => {
    const blocks = [
      block('b1', 'House', '2026-05-04', 42),
      block('b2', 'Techno', '2026-04-27', 88),
    ];
    render(wrap(<ActiveBlocksList blocks={blocks} total={2} />));
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('88')).toBeInTheDocument();
    expect(screen.getByText(/2026-W19/)).toBeInTheDocument();
    expect(screen.queryByText(/View all/)).toBeNull();
  });

  it('shows the View all footer when total exceeds the rendered slice', () => {
    const blocks = [block('b1', 'House', '2026-05-04', 10)];
    render(wrap(<ActiveBlocksList blocks={blocks} total={9} />));
    const link = screen.getByRole('link', { name: /View all \(9 blocks\)/ });
    expect(link.getAttribute('href')).toBe('/triage');
  });

  it('renders an empty hint when there are no blocks', () => {
    render(wrap(<ActiveBlocksList blocks={[]} total={0} />));
    expect(screen.getByText(/Nothing in progress/)).toBeInTheDocument();
  });
});
