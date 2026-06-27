import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAnalytics } from '../useAnalytics';

const apiMock = vi.hoisted(() => vi.fn());
vi.mock('../../../../api/client', () => ({ api: (...a: unknown[]) => apiMock(...a) }));

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useAnalytics', () => {
  it('fetches the /v1 dashboard route with the date range and returns rows', async () => {
    apiMock.mockResolvedValue({ rows: [{ date: '2026-01-02', decisions: 5 }] });
    const { result } = renderHook(
      () => useAnalytics('triage', { from: '2026-01-01', to: '2026-02-01' }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock).toHaveBeenCalledWith(
      '/v1/analytics/triage?from=2026-01-01&to=2026-02-01',
    );
    expect(result.current.data?.rows[0]).toMatchObject({ decisions: 5 });
  });

  it('surfaces error state', async () => {
    apiMock.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(
      () => useAnalytics('ops', { from: '2026-01-01', to: '2026-02-01' }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
