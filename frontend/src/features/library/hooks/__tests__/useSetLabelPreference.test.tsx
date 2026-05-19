import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useSetLabelPreference } from '../useSetLabelPreference';

function wrap(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe('useSetLabelPreference', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('patches labelInfo cache optimistically and on success', async () => {
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    qc.setQueryData(['labelInfo', 'lbl-1'], { label_name: 'Fokuz', my_preference: null });

    const { result } = renderHook(() => useSetLabelPreference(), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({ labelId: 'lbl-1', status: 'liked' });
    });

    const cached = qc.getQueryData<{ my_preference: string | null }>(['labelInfo', 'lbl-1']);
    expect(cached?.my_preference).toBe('liked');
  });

  it('rolls back labelInfo on error', async () => {
    server.use(
      http.put('http://localhost/labels/lbl-1/preference', () =>
        HttpResponse.json({ error_code: 'boom', message: 'no' }, { status: 500 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    qc.setQueryData(['labelInfo', 'lbl-1'], { label_name: 'Fokuz', my_preference: null });

    const { result } = renderHook(() => useSetLabelPreference(), { wrapper: wrap(qc) });
    await act(async () => {
      try {
        await result.current.mutateAsync({ labelId: 'lbl-1', status: 'liked' });
      } catch {
        // expected
      }
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = qc.getQueryData<{ my_preference: string | null }>(['labelInfo', 'lbl-1']);
    expect(cached?.my_preference).toBeNull();
  });
});
