import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { useMe } from '../useMe';
import { tokenStore } from '../../../auth/tokenStore';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useMe', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('returns user on success', async () => {
    server.use(
      http.get('http://localhost/me', () =>
        HttpResponse.json({
          id: 'u1',
          spotify_id: 'sp1',
          display_name: 'Roman',
          is_admin: false,
        }),
      ),
    );
    const { result } = renderHook(() => useMe(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.display_name).toBe('Roman');
  });

  it('reports error on failure', async () => {
    server.use(
      http.get('http://localhost/me', () =>
        HttpResponse.json(
          { error_code: 'forbidden', message: 'no', correlation_id: 'c' },
          { status: 403 },
        ),
      ),
    );
    const { result } = renderHook(() => useMe(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
