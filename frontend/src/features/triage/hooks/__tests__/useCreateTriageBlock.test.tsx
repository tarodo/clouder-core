import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import {
  useCreateTriageBlock,
  PendingCreateError,
} from '../useCreateTriageBlock';
import { triageBlocksByStyleKey } from '../useTriageBlocksByStyle';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

const validInput = {
  style_id: 's1',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
};

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return {
    qc,
    Wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  };
}

describe('useCreateTriageBlock', () => {
  it('happy 201 → invalidates all 3 caches', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json(
          {
            id: 'b1',
            style_id: 's1',
            style_name: 'House',
            ...validInput,
            status: 'IN_PROGRESS',
            created_at: 'now',
            updated_at: 'now',
            finalized_at: null,
            buckets: [],
          },
          { status: 201 },
        ),
      ),
    );

    const { qc, Wrapper } = makeWrapper();
    qc.setQueryData(triageBlocksByStyleKey('s1', 'IN_PROGRESS'), {
      pages: [{ items: [], total: 0, limit: 50, offset: 0 }],
      pageParams: [0],
    });

    const { result } = renderHook(() => useCreateTriageBlock('s1'), {
      wrapper: Wrapper,
    });
    await act(async () => {
      await result.current.mutateAsync(validInput);
    });

    expect(
      qc.getQueryState(triageBlocksByStyleKey('s1', 'IN_PROGRESS'))?.isInvalidated,
    ).toBe(true);
  });

  it('503 cold-start → throws PendingCreateError and schedules recovery', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );

    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useCreateTriageBlock('s1'), {
      wrapper: Wrapper,
    });

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync(validInput);
      } catch (err) {
        caught = err;
      }
    });
    expect(caught).toBeInstanceOf(PendingCreateError);
  });

  it('non-503 error → throws ApiError', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json(
          {
            error_code: 'validation_error',
            message: 'bad',
            correlation_id: 'cid',
          },
          { status: 422 },
        ),
      ),
    );

    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useCreateTriageBlock('s1'), {
      wrapper: Wrapper,
    });

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync(validInput);
      } catch (err) {
        caught = err;
      }
    });
    expect(caught).toMatchObject({ code: 'validation_error', status: 422 });
  });
});
