import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { UserDailyTable, SessionsTable } from '../AnalyticsDashboard';

// jsdom has no layout — stub the charts lib.
vi.mock('@mantine/charts', () => ({
  LineChart: () => <div data-testid="line-chart" />,
}));

const range = { from: '2026-01-01', to: '2026-02-01' };

// --- useUserDaily mock ---
const useUserDailyMock = vi.hoisted(() => vi.fn());
// --- useSessionsMock ---
const useSessionsMock = vi.hoisted(() => vi.fn());

vi.mock('../../hooks/useAnalytics', () => ({
  useUserDaily: (...a: unknown[]) => useUserDailyMock(...a),
  useSessions: (...a: unknown[]) => useSessionsMock(...a),
}));

function wrap(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('UserDailyTable', () => {
  it('shows loading state', () => {
    useUserDailyMock.mockReturnValue({ isLoading: true, isError: false, data: undefined });
    wrap(<UserDailyTable userId="u1" range={range} />);
    expect(document.querySelector('[data-testid="loader"]') ?? screen.queryByRole('status')).not.toBeNull();
  });

  it('shows error state', () => {
    useUserDailyMock.mockReturnValue({ isLoading: false, isError: true, data: undefined });
    wrap(<UserDailyTable userId="u1" range={range} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('renders rows from user-daily payload', () => {
    useUserDailyMock.mockReturnValue({
      isLoading: false, isError: false,
      data: {
        'user-daily': [
          {
            user_id: 'u1', activity_type: 'triage', dt: '2026-01-10',
            sessions: '3', avg_tracks_listened: '12', avg_tracks_promoted: '4',
            avg_tracks_deleted: '2', p50_duration_ms: '120000', p90_duration_ms: '200000',
            p50_time_per_track_ms: '5000', p90_time_per_track_ms: '9000',
          },
          {
            user_id: 'u1', activity_type: 'playlist', dt: '2026-01-11',
            sessions: '1', avg_tracks_listened: null, avg_tracks_promoted: null,
            avg_tracks_deleted: null, p50_duration_ms: '60000', p90_duration_ms: '90000',
            p50_time_per_track_ms: null, p90_time_per_track_ms: null,
          },
        ],
      },
    });
    wrap(<UserDailyTable userId="u1" range={range} />);
    // date and activity appear
    expect(screen.getByText('2026-01-10')).toBeInTheDocument();
    expect(screen.getByText('triage')).toBeInTheDocument();
    // sessions rendered (not raw string "3", but number 3)
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
    // playlist NULL averages render as em-dash, not "null" or "NaN"
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThan(0);
    expect(screen.queryByText('null')).toBeNull();
    expect(screen.queryByText('NaN')).toBeNull();
  });

  it('coerces p50_duration_ms string "120000" to a numeric display (not raw string)', () => {
    useUserDailyMock.mockReturnValue({
      isLoading: false, isError: false,
      data: {
        'user-daily': [
          {
            user_id: 'u1', activity_type: 'triage', dt: '2026-01-10',
            sessions: '1', avg_tracks_listened: null, avg_tracks_promoted: null,
            avg_tracks_deleted: null, p50_duration_ms: '120000', p90_duration_ms: null,
            p50_time_per_track_ms: null, p90_time_per_track_ms: null,
          },
        ],
      },
    });
    wrap(<UserDailyTable userId="u1" range={range} />);
    // Should NOT render the raw string "120000" as-is in the p50 column
    // (it gets formatted to "2:00" or "120s" etc.). Confirm it's not the raw value:
    // We check the formatted representation — fmtMs(120000) = "2:00"
    expect(screen.getByText('2:00')).toBeInTheDocument();
  });

  it('shows empty state when no rows', () => {
    useUserDailyMock.mockReturnValue({
      isLoading: false, isError: false,
      data: { 'user-daily': [] },
    });
    wrap(<UserDailyTable userId="u1" range={range} />);
    // empty state text from i18n key admin.analytics.empty
    expect(screen.getByText(/No data/i)).toBeInTheDocument();
  });
});

describe('SessionsTable', () => {
  it('renders session rows', () => {
    useSessionsMock.mockReturnValue({
      isLoading: false, isError: false,
      data: {
        sessions: [
          {
            user_id: 'u1', activity_type: 'triage', dt: '2026-01-10', session_seq: '1',
            ts_start: '2026-01-10T12:00:00', ts_end: '2026-01-10T12:30:00',
            duration_ms: '1800000', tracks_listened: '10', tracks_promoted: '3', tracks_deleted: '1',
          },
        ],
      },
    });
    wrap(<SessionsTable userId="u1" range={range} />);
    expect(screen.getByText('2026-01-10')).toBeInTheDocument();
    expect(screen.getByText('2026-01-10T12:00:00')).toBeInTheDocument();
    // duration formatted (1800000ms = 30:00)
    expect(screen.getByText('30:00')).toBeInTheDocument();
  });

  it('renders NULL fields as em-dash', () => {
    useSessionsMock.mockReturnValue({
      isLoading: false, isError: false,
      data: {
        sessions: [
          {
            user_id: 'u1', activity_type: 'playlist', dt: '2026-01-10', session_seq: null,
            ts_start: null, ts_end: null, duration_ms: '600000',
            tracks_listened: null, tracks_promoted: null, tracks_deleted: null,
          },
        ],
      },
    });
    wrap(<SessionsTable userId="u1" range={range} />);
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThan(0);
    expect(screen.queryByText('null')).toBeNull();
  });
});
