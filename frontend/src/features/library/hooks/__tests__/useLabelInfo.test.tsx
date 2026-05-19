import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useLabelInfo, labelInfoKey } from '../useLabelInfo';
import { labelDetailKey } from '../useLabelDetail';

describe('useLabelInfo', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('uses a different cache key than useLabelDetail', () => {
    expect(labelInfoKey('x')).not.toEqual(labelDetailKey('x'));
  });

  it('returns error result silently on 404', async () => {
    server.use(
      http.get('http://localhost/labels/x', () =>
        HttpResponse.json({ error_code: 'label_not_found', message: 'nope' }, { status: 404 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLabelInfo('x'), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
