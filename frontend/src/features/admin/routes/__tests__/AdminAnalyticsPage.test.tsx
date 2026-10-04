import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AdminAnalyticsPage } from '../AdminAnalyticsPage';

const listening = {
  today: '2026-10-05',
  totals: {
    day: { listened_ms: 0, tracks: 0 },
    week: { listened_ms: 5_040_000, tracks: 80 }, // 84 min
    month: { listened_ms: 16_800_000, tracks: 887 }, // 280 min
  },
  daily: [{ dt: '2026-10-05', listened_ms: 0, tracks: 0 }],
};

const funnel = {
  today: '2026-10-05',
  stages: [
    { stage: 'triaged', day: 0, week: 500, month: 1000 },
    { stage: 'categorized', day: 0, week: 40, month: 100 },
    { stage: 'playlisted', day: 0, week: 2, month: 10 },
  ],
};

vi.mock('../../hooks/useAnalytics', () => ({
  useListening: () => ({ data: listening, isLoading: false, isError: false }),
  useFunnel: () => ({ data: funnel, isLoading: false, isError: false }),
}));

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
  it('shows listening minutes and track counts per period', () => {
    renderPage();
    const week = within(screen.getByTestId('listening-week'));
    expect(week.getByText('1 h 24 min')).toBeDefined();
    expect(week.getByText('80 tracks')).toBeDefined();
    const month = within(screen.getByTestId('listening-month'));
    expect(month.getByText('4 h 40 min')).toBeDefined();
    expect(month.getByText('887 tracks')).toBeDefined();
    expect(within(screen.getByTestId('listening-day')).getByText('0 min')).toBeDefined();
  });

  it('shows the 30-day funnel with step conversion by default', () => {
    renderPage();
    expect(within(screen.getByTestId('funnel-triaged')).getByText('1000')).toBeDefined();
    const cat = within(screen.getByTestId('funnel-categorized'));
    expect(cat.getByText('100')).toBeDefined();
    expect(cat.getByText('10% of previous')).toBeDefined();
    expect(within(screen.getByTestId('funnel-playlisted')).getByText('10% of previous')).toBeDefined();
  });

  it('switches the funnel period', async () => {
    renderPage();
    await userEvent.click(screen.getByRole('radio', { name: 'Last 7 days' }));
    expect(within(screen.getByTestId('funnel-triaged')).getByText('500')).toBeDefined();
    expect(within(screen.getByTestId('funnel-categorized')).getByText('8% of previous')).toBeDefined();
  });
});
