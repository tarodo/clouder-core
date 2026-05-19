import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../../../i18n';
import { tokenStore } from '../../../../auth/tokenStore';
import type { LabelSummary } from '../../../../api/labels';
import { LabelsTable } from '../LabelsTable';

function renderTable(items: LabelSummary[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <LabelsTable
              items={items}
              styleId="dnb"
              isLoading={false}
              page={1}
              pageCount={1}
              onPageChange={() => {}}
            />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('LabelsTable My column', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders preference buttons in each row', () => {
    renderTable([
      {
        id: 'lbl-1', name: 'Fokuz', style: 'dnb', status: 'completed',
        track_count: 142, info: { tagline: 't', country: 'NL', founded_year: 2007,
          primary_styles: ['liquid'], activity: 'steady',
          ai_content: 'none_detected', updated_at: '2026-05-19T00:00:00Z',
        },
        my_preference: 'liked',
      },
    ]);
    expect(screen.getByText('My')).toBeInTheDocument();
    // active heart → aria switches to "Remove preference"
    expect(screen.getByRole('button', { name: /^remove preference$/i })).toBeInTheDocument();
  });
});
