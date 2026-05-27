import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { useSetArtistPreference } from '../useSetArtistPreference';
import { artistInfoKey } from '../useArtistInfo';
import { artistDetailKey } from '../useArtistDetail';
import * as client from '../../../../api/client';

function wrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useSetArtistPreference', () => {
  beforeEach(() => vi.restoreAllMocks());

  test('PUTs status and optimistically patches info, detail, and list caches', async () => {
    const apiSpy = vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    qc.setQueryData(artistInfoKey('a1'), { artist_name: 'A1', my_preference: null });
    qc.setQueryData(artistDetailKey('a1'), { artist_name: 'A1', my_preference: null });
    qc.setQueryData(
      ['library', 'artists', 'techno', '', 'name', 'all', 1, 25],
      { items: [{ id: 'a1', name: 'A1', my_preference: null }], total: 1, page: 1, limit: 25 },
    );

    const { result } = renderHook(() => useSetArtistPreference(), { wrapper: wrapper(qc) });
    result.current.mutate({ artistId: 'a1', status: 'liked' });

    await waitFor(() => {
      expect((qc.getQueryData(artistInfoKey('a1')) as { my_preference?: string }).my_preference).toBe('liked');
    });
    expect((qc.getQueryData(artistDetailKey('a1')) as { my_preference?: string }).my_preference).toBe('liked');
    const list = qc.getQueryData(['library', 'artists', 'techno', '', 'name', 'all', 1, 25]) as
      | { items: Array<{ id: string; my_preference?: string | null }> }
      | undefined;
    expect(list!.items[0]!.my_preference).toBe('liked');
    expect(apiSpy).toHaveBeenCalledWith('/artists/a1/preference', {
      method: 'PUT',
      body: JSON.stringify({ status: 'liked' }),
    });
  });

  test('rolls back caches when the request fails', async () => {
    vi.spyOn(client, 'api').mockRejectedValue(new Error('boom'));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(artistInfoKey('a1'), { artist_name: 'A1', my_preference: null });

    const { result } = renderHook(() => useSetArtistPreference(), { wrapper: wrapper(qc) });
    result.current.mutate({ artistId: 'a1', status: 'disliked' });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((qc.getQueryData(artistInfoKey('a1')) as { my_preference?: string | null }).my_preference).toBe(null);
  });
});
