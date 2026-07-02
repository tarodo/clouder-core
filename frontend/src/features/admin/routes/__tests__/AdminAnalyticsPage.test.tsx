import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AdminAnalyticsPage } from '../AdminAnalyticsPage';

vi.mock('../../hooks/useAnalytics', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../hooks/useAnalytics')>();
  return {
    ...actual,
    useUsers: () => ({
      data: {
        users: [
          { id: 'u1', display_name: 'Alice' },
          { id: 'u2', display_name: 'Bob' },
        ],
      },
      isLoading: false,
    }),
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <AdminAnalyticsPage />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AdminAnalyticsPage', () => {
  it('shows pick_user prompt when no user selected', () => {
    renderPage();
    expect(screen.getByText(/select a user/i)).toBeDefined();
  });

  it('renders a Select for user picker (not a plain text input)', () => {
    renderPage();
    // Mantine Select renders a combobox role
    const combo = screen.getByRole('combobox');
    expect(combo).toBeDefined();
  });

  it('renders two date inputs with labels', () => {
    renderPage();
    expect(screen.getByLabelText(/from/i)).toBeDefined();
    expect(screen.getByLabelText(/to/i)).toBeDefined();
  });
});
