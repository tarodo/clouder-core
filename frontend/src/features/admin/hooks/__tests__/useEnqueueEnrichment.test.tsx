import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useEnqueueEnrichment } from '../useEnqueueEnrichment';

describe('useEnqueueEnrichment', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs the enrich body and returns run_id', async () => {
    server.use(
      http.post('http://localhost/admin/labels/enrich', () =>
        HttpResponse.json({ run_id: 'r-1', queued_labels: 3 }, { status: 202 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useEnqueueEnrichment(), { wrapper });
    const promise = result.current.mutateAsync({
      labels: [{ label_id: 'l1' }],
      vendors: ['gemini'],
      models: { gemini: 'gemini-2.5-pro' },
      prompt_slug: 'label_v3_app_fields',
      prompt_version: 'v1',
      merge_vendor: 'deepseek',
      merge_model: 'deepseek-chat',
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const res = await promise;
    expect(res.run_id).toBe('r-1');
  });
});
