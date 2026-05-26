import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { AdminEnrichmentRunsPage } from '../AdminEnrichmentRunsPage';

// i18n is initialized globally in src/test/setup.ts

// `pages` is built ONCE inside the factory closure so the hook returns a stable
// reference across renders — matching real TanStack Query behaviour. A fresh object
// per call would change [query.data] effect deps every render and loop forever.
const mockPages = {
  pages: [
    {
      items: [
        {
          id: 'aaaaaaaa-0000-0000-0000-000000000000',
          status: 'completed',
          source: 'manual',
          created_at: '2026-01-01T00:00:00Z',
          cells_ok: 3,
          cells_error: 0,
          cells_total: 3,
          cost_usd: 0.0042,
        },
        {
          id: 'bbbbbbbb-0000-0000-0000-000000000000',
          status: 'completed',
          source: 'auto',
          created_at: '2026-01-02T00:00:00Z',
          cells_ok: 5,
          cells_error: 1,
          cells_total: 6,
          cost_usd: null,
        },
      ],
      next_cursor: null,
    },
  ],
  pageParams: [undefined],
};

vi.mock('../../hooks/useEnrichmentRuns', () => ({
  useEnrichmentRuns: () => ({
    data: mockPages,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  }),
}));

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <MantineProvider>
          <AdminEnrichmentRunsPage />
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('AdminEnrichmentRunsPage', () => {
  it('renders runs table with source badges', () => {
    renderPage();
    // Both source values should appear as badges
    expect(screen.getByText('manual')).toBeTruthy();
    expect(screen.getByText('auto')).toBeTruthy();
  });

  it('renders source filter segmented control', () => {
    renderPage();
    expect(screen.getByText('All')).toBeTruthy();
    expect(screen.getByText('Manual')).toBeTruthy();
    expect(screen.getByText('Auto')).toBeTruthy();
  });

  it('renders status filter select', () => {
    renderPage();
    // "Status" appears as Select label and table column header — at least one must exist
    expect(screen.getAllByText('Status').length).toBeGreaterThan(0);
  });

  it('shows source column header', () => {
    renderPage();
    // "Source" appears as the filter label and table column header
    expect(screen.getAllByText('Source').length).toBeGreaterThan(0);
  });

  it('shows both run ids truncated to 8 chars', () => {
    renderPage();
    expect(screen.getByText('aaaaaaaa')).toBeTruthy();
    expect(screen.getByText('bbbbbbbb')).toBeTruthy();
  });

  it('changing source filter segment does not crash', () => {
    renderPage();
    const autoBtn = screen.getByText('Auto');
    fireEvent.click(autoBtn);
    // After clicking, the control stays rendered — no crash
    expect(screen.getByText('Auto')).toBeTruthy();
  });
});
