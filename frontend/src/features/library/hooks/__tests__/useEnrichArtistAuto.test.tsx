import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useEnrichArtistAuto } from '../useEnrichArtistAuto';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </I18nextProvider>
  );
}

describe('useEnrichArtistAuto', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs to the enrich-auto endpoint and resolves with the run id', async () => {
    let hit = '';
    server.use(
      http.post('http://localhost/admin/artists/:id/enrich-auto', ({ params }) => {
        hit = String(params.id);
        return HttpResponse.json({ run_id: 'run-1', queued_artists: 1 }, { status: 202 });
      }),
    );
    const { result } = renderHook(() => useEnrichArtistAuto(), { wrapper });
    result.current.mutate({ artistId: 'art-1' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(hit).toBe('art-1');
    expect(result.current.data).toEqual({ run_id: 'run-1', queued_artists: 1 });
  });
});
