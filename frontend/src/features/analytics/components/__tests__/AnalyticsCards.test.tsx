import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import {
  FunnelCard,
  ListeningCard,
  TimePerTrackCard,
  fmtCount,
  fmtMinutes,
  fmtSec,
} from '../AnalyticsCards';

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

const state = vi.hoisted(() => ({ loading: false, tptDays: [] as number[] }));

const tpt = {
  days: 30,
  stages: ['triage', 'category', 'playlist'],
  rows: [
    {
      style_id: '*',
      style_name: null,
      cells: {
        triage: { n: 2303, p50_ms: 6143, p90_ms: 29947 },
        category: { n: 608, p50_ms: 84000, p90_ms: 88297 },
        playlist: null,
      },
    },
    {
      style_id: 'h',
      style_name: 'House',
      cells: { triage: { n: 5, p50_ms: 72629, p90_ms: 195433 }, category: null, playlist: null },
    },
    {
      style_id: null,
      style_name: null,
      cells: { triage: null, category: null, playlist: { n: 8, p50_ms: 83854, p90_ms: 208333 } },
    },
  ],
};

vi.mock('../../hooks/useAnalytics', () => ({
  useListening: () =>
    state.loading
      ? { data: undefined, isLoading: true, isError: false }
      : { data: listening, isLoading: false, isError: false },
  useFunnel: () =>
    state.loading
      ? { data: undefined, isLoading: true, isError: false }
      : { data: funnel, isLoading: false, isError: false },
  useTimePerTrack: (_userId: string, days: number) => {
    state.tptDays.push(days);
    return state.loading
      ? { data: undefined, isLoading: true, isError: false }
      : { data: tpt, isLoading: false, isError: false };
  },
}));

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

describe('analytics cards', () => {
  afterEach(() => {
    state.loading = false;
  });

  it('shows gray skeleton blocks, not a spinner, while loading', () => {
    state.loading = true;
    wrap(
      <>
        <ListeningCard />
        <FunnelCard />
      </>,
    );
    expect(screen.getByTestId('listening-skeleton')).toBeDefined();
    expect(screen.getByTestId('funnel-skeleton')).toBeDefined();
    expect(screen.queryByTestId('loader')).toBeNull();
  });

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

  it('formats per-track time and play counts compactly', () => {
    expect(fmtSec(6143)).toBe('6s');
    expect(fmtSec(84000)).toBe('84s');
    expect(fmtSec(208333)).toBe('208s');
    expect(fmtSec(720000)).toBe('12m');
    expect(fmtCount(980)).toBe('980');
    expect(fmtCount(2303)).toBe('2.3k');
    expect(fmtCount(12345)).toBe('12k');
  });

  it('shows the stage x style matrix: median, p90 · plays, unknown style last', () => {
    wrap(<TimePerTrackCard />);
    const all = within(screen.getByTestId('tpt-*-triage'));
    expect(all.getByText('6s')).toBeDefined();
    expect(all.getByText('30s · 2.3k')).toBeDefined();
    expect(within(screen.getByTestId('tpt-*-category')).getByText('84s')).toBeDefined();
    expect(within(screen.getByTestId('tpt-*-playlist')).getByText('—')).toBeDefined();
    // 5 plays < 20: p90 hidden
    expect(within(screen.getByTestId('tpt-h-triage')).getByText('— · 5')).toBeDefined();
    expect(screen.getByText('All styles')).toBeDefined();
    expect(screen.getByText('House')).toBeDefined();
    expect(screen.getByText('Unknown style')).toBeDefined();
  });

  it('switches the window to 90 days', async () => {
    state.tptDays = [];
    wrap(<TimePerTrackCard />);
    expect(state.tptDays.at(-1)).toBe(30);
    await userEvent.click(screen.getByRole('radio', { name: '90 days' }));
    expect(state.tptDays.at(-1)).toBe(90);
  });
});
