import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { useCreatePlaylist } from '../useCreatePlaylist';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useCreatePlaylist', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists', async ({ request }) => {
        const body = (await request.json()) as { name: string };
        return HttpResponse.json(
          {
            id: 'p1',
            user_id: 'u1',
            name: body.name,
            description: null,
            is_public: false,
            cover_s3_key: null,
            cover_url: null,
            cover_uploaded_at: null,
            spotify_playlist_id: null,
            last_published_at: null,
            needs_republish: false,
            track_count: 0,
            created_at: '2026-05-12T00:00:00Z',
            updated_at: '2026-05-12T00:00:00Z',
          },
          { status: 201 },
        );
      }),
    );
  });

  it('invalidates the playlists list after success', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useCreatePlaylist(), { wrapper: makeWrapper(qc) });
    await result.current.mutateAsync({ name: 'Hello', is_public: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(
      invalidateSpy.mock.calls.some(
        ([arg]) =>
          Array.isArray(arg?.queryKey) &&
          arg.queryKey[0] === 'playlists' &&
          arg.queryKey[1] === 'list',
      ),
    ).toBe(true);
  });
});
