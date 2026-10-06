import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { FunnelCard, ListeningCard, fmtMinutes } from '../AnalyticsCards';

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

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

describe('analytics cards', () => {
  it('formats minutes compactly', () => {
    expect(fmtMinutes(0)).toBe('0m');
    expect(fmtMinutes(42 * 60_000)).toBe('42m');
    expect(fmtMinutes(280 * 60_000)).toBe('4h 40m');
  });

  it('shows listening minutes and track counts per period', () => {
    wrap(<ListeningCard />);
    const week = within(screen.getByTestId('listening-week'));
    expect(week.getByText('1h 24m')).toBeDefined();
    expect(week.getByText('80 tracks')).toBeDefined();
    const month = within(screen.getByTestId('listening-month'));
    expect(month.getByText('4h 40m')).toBeDefined();
    expect(month.getByText('887 tracks')).toBeDefined();
    expect(within(screen.getByTestId('listening-day')).getByText('0m')).toBeDefined();
  });

  it('shows the 30-day funnel with step conversion by default', () => {
    wrap(<FunnelCard />);
    expect(within(screen.getByTestId('funnel-triaged')).getByText('1000')).toBeDefined();
    const cat = within(screen.getByTestId('funnel-categorized'));
    expect(cat.getByText('100')).toBeDefined();
    expect(cat.getByText('10% of previous')).toBeDefined();
    expect(within(screen.getByTestId('funnel-playlisted')).getByText('10% of previous')).toBeDefined();
  });

  it('switches the funnel period', async () => {
    wrap(<FunnelCard />);
    await userEvent.click(screen.getByRole('radio', { name: '7 days' }));
    expect(within(screen.getByTestId('funnel-triaged')).getByText('500')).toBeDefined();
    expect(within(screen.getByTestId('funnel-categorized')).getByText('8% of previous')).toBeDefined();
  });
});
