import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { tzOffsetMin, useFunnel, useListening } from '../useAnalytics';

const apiMock = vi.hoisted(() => vi.fn());
vi.mock('../../../../api/client', () => ({ api: (...a: unknown[]) => apiMock(...a) }));

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => apiMock.mockReset());

describe('analytics hooks', () => {
  it('useListening passes the browser tz offset', async () => {
    apiMock.mockResolvedValue({ today: '2026-10-05', totals: {}, daily: [] });
    const { result } = renderHook(() => useListening(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock).toHaveBeenCalledWith(`/v1/analytics/listening?tz_offset_min=${tzOffsetMin()}`);
  });

  it('passes user_id when an admin picks a user', async () => {
    apiMock.mockResolvedValue({ today: '2026-10-05', stages: [] });
    const { result } = renderHook(() => useFunnel('u 1'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock).toHaveBeenCalledWith(
      `/v1/analytics/funnel?tz_offset_min=${tzOffsetMin()}&user_id=u%201`,
    );
  });

  it('useFunnel hits the funnel route', async () => {
    apiMock.mockResolvedValue({ today: '2026-10-05', stages: [] });
    const { result } = renderHook(() => useFunnel(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock).toHaveBeenCalledWith(`/v1/analytics/funnel?tz_offset_min=${tzOffsetMin()}`);
  });
});
