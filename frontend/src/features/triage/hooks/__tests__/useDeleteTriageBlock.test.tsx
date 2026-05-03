import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { useDeleteTriageBlock } from '../useDeleteTriageBlock';
import { triageBlocksByStyleKey } from '../useTriageBlocksByStyle';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

describe('useDeleteTriageBlock', () => {
  it('invalidates all 3 status caches on success', async () => {
    server.use(
      http.delete('http://localhost/triage/blocks/b1', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );

    const qc = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    qc.setQueryData(triageBlocksByStyleKey('s1', 'IN_PROGRESS'), {
      pages: [{ items: [{ id: 'b1' }], total: 1, limit: 50, offset: 0 }],
      pageParams: [0],
    });
    qc.setQueryData(triageBlocksByStyleKey('s1', 'FINALIZED'), {
      pages: [{ items: [], total: 0, limit: 50, offset: 0 }],
      pageParams: [0],
    });
    qc.setQueryData(triageBlocksByStyleKey('s1', undefined), {
      pages: [{ items: [{ id: 'b1' }], total: 1, limit: 50, offset: 0 }],
      pageParams: [0],
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDeleteTriageBlock('s1'), {
      wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync('b1');
    });

    expect(qc.getQueryState(triageBlocksByStyleKey('s1', 'IN_PROGRESS'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(triageBlocksByStyleKey('s1', 'FINALIZED'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(triageBlocksByStyleKey('s1', undefined))?.isInvalidated).toBe(true);
  });

  it('throws ApiError on 404', async () => {
    server.use(
      http.delete('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json(
          { error_code: 'triage_block_not_found', message: 'Not found', correlation_id: 'cid' },
          { status: 404 },
        ),
      ),
    );

    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDeleteTriageBlock('s1'), { wrapper });

    await expect(
      act(async () => {
        await result.current.mutateAsync('b1');
      }),
    ).rejects.toMatchObject({ code: 'triage_block_not_found', status: 404 });
  });
});
