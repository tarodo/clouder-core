import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useLabelDetail } from '../useLabelDetail';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useLabelDetail', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('does not fetch when labelId is null', () => {
    const { result } = renderHook(() => useLabelDetail(null), { wrapper: wrap() });
    expect(result.current.fetchStatus).toBe('idle');
  });

  it('fetches detail when labelId is present', async () => {
    server.use(
      http.get('http://localhost/labels/abc', () =>
        HttpResponse.json({ label_name: 'Fokuz', country: 'NL' }),
      ),
    );
    const { result } = renderHook(() => useLabelDetail('abc'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.label_name).toBe('Fokuz');
  });
});
