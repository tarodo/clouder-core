import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { AdminArtistEnrichmentRunsPage } from '../AdminArtistEnrichmentRunsPage';

// i18n is initialized globally in src/test/setup.ts

// `pages` is built ONCE inside the factory closure so the hook returns a stable
// reference across renders — matching real TanStack Query behaviour.
const mockPages = {
  pages: [
    {
      items: [
        {
          id: 'cccccccc-0000-0000-0000-000000000000',
          status: 'completed',
          source: 'manual',
          created_at: '2026-01-01T00:00:00Z',
          cells_ok: 3,
          cells_error: 0,
          cells_total: 3,
          cost_usd: 0.0042,
        },
        {
          id: 'dddddddd-0000-0000-0000-000000000000',
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

vi.mock('../../hooks/useArtistEnrichmentRuns', () => ({
  useArtistEnrichmentRuns: () => ({
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
          <AdminArtistEnrichmentRunsPage />
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('AdminArtistEnrichmentRunsPage', () => {
  it('renders runs table with links to /admin/artists/enrich/runs/:runId', () => {
    renderPage();
    // Run IDs truncated to 8 chars as anchors linking to artist runs
    const linkA = screen.getByText('cccccccc');
    expect(linkA.closest('a')).toHaveProperty('href');
    expect(linkA.closest('a')?.getAttribute('href')).toContain('/admin/artists/enrich/runs/cccccccc');

    const linkB = screen.getByText('dddddddd');
    expect(linkB.closest('a')?.getAttribute('href')).toContain('/admin/artists/enrich/runs/dddddddd');
  });

  it('renders runs table with source badges', () => {
    renderPage();
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
    expect(screen.getAllByText('Status').length).toBeGreaterThan(0);
  });

  it('shows both run ids truncated to 8 chars', () => {
    renderPage();
    expect(screen.getByText('cccccccc')).toBeTruthy();
    expect(screen.getByText('dddddddd')).toBeTruthy();
  });

  it('changing source filter segment does not crash', () => {
    renderPage();
    const autoBtn = screen.getByText('Auto');
    fireEvent.click(autoBtn);
    expect(screen.getByText('Auto')).toBeTruthy();
  });
});
