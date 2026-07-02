import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useUserDaily, useSessions } from '../useAnalytics';

const apiMock = vi.hoisted(() => vi.fn());
vi.mock('../../../../api/client', () => ({ api: (...a: unknown[]) => apiMock(...a) }));

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => apiMock.mockReset());

const range = { from: '2026-01-01', to: '2026-02-01' };

describe('useUserDaily', () => {
  it('fetches /v1/analytics/user-daily with user_id + range', async () => {
    const row = { user_id: 'u1', activity_type: 'triage', dt: '2026-01-02', sessions: '3',
      avg_tracks_listened: null, avg_tracks_promoted: null, avg_tracks_deleted: null,
      p50_duration_ms: '120000', p90_duration_ms: null, p50_time_per_track_ms: null, p90_time_per_track_ms: null };
    apiMock.mockResolvedValue({ 'user-daily': [row] });
    const { result } = renderHook(() => useUserDaily('u1', range), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock).toHaveBeenCalledWith(
      '/v1/analytics/user-daily?user_id=u1&from=2026-01-01&to=2026-02-01',
    );
    expect(result.current.data?.['user-daily'][0]).toMatchObject({ sessions: '3' });
  });

  it('does not fetch when userId is empty', () => {
    apiMock.mockResolvedValue({ 'user-daily': [] });
    const { result } = renderHook(() => useUserDaily('', range), { wrapper });
    expect(result.current.fetchStatus).toBe('idle');
    expect(apiMock).not.toHaveBeenCalled();
  });

  it('surfaces error state', async () => {
    // Suppress TanStack Query's console.error for the rejected promise.
    vi.spyOn(console, 'error').mockImplementation(() => {});
    apiMock.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useUserDaily('u1', range), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    vi.restoreAllMocks();
  });
});

describe('useSessions', () => {
  it('fetches /v1/analytics/sessions with user_id + range', async () => {
    apiMock.mockResolvedValue({ sessions: [] });
    const { result } = renderHook(() => useSessions('u1', range), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock).toHaveBeenCalledWith(
      '/v1/analytics/sessions?user_id=u1&from=2026-01-01&to=2026-02-01',
    );
  });

  it('does not fetch when userId is empty', () => {
    apiMock.mockResolvedValue({ sessions: [] });
    const { result } = renderHook(() => useSessions('  ', range), { wrapper });
    expect(result.current.fetchStatus).toBe('idle');
  });
});
