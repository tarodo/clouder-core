import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { useUploadCover } from '../useUploadCover';

function makeWrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe('useUploadCover', () => {
  beforeEach(() => {
    server.use(
      http.post('http://localhost/playlists/p1/cover/upload-url', () =>
        HttpResponse.json({
          upload_url: 'https://s3.example/PUT',
          s3_key: 'covers/u1/p1/abc.jpg',
          expires_in: 300,
        }),
      ),
      http.put('https://s3.example/PUT', () => new HttpResponse(null, { status: 200 })),
      http.post('http://localhost/playlists/p1/cover/confirm', async ({ request }) => {
        const body = (await request.json()) as { s3_key: string };
        expect(body.s3_key).toBe('covers/u1/p1/abc.jpg');
        return HttpResponse.json({
          id: 'p1',
          user_id: 'u1',
          name: 'P1',
          description: null,
          is_public: false,
          cover_s3_key: 'covers/u1/p1/abc.jpg',
          cover_url: 'https://s3.example/GET',
          cover_uploaded_at: '2026-05-12T00:00:00Z',
          spotify_playlist_id: null,
          last_published_at: null,
          needs_republish: false,
          track_count: 0,
          created_at: '2026-05-12T00:00:00Z',
          updated_at: '2026-05-12T00:00:00Z',
        });
      }),
    );
  });

  it('runs presign → PUT → confirm and returns the updated playlist', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUploadCover(), { wrapper: makeWrapper(qc) });
    const file = new File(['xxx'], 'cover.jpg', { type: 'image/jpeg' });
    const out = await result.current.mutateAsync({ playlistId: 'p1', file });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(out.cover_s3_key).toBe('covers/u1/p1/abc.jpg');
  });

  it('rejects files larger than 256KB on the client', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUploadCover(), { wrapper: makeWrapper(qc) });
    const huge = new File([new Uint8Array(300_000)], 'big.jpg', { type: 'image/jpeg' });
    await expect(
      result.current.mutateAsync({ playlistId: 'p1', file: huge }),
    ).rejects.toThrow(/too large/i);
  });

  it('rejects non-jpeg/png types on the client', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUploadCover(), { wrapper: makeWrapper(qc) });
    const gif = new File(['x'], 'a.gif', { type: 'image/gif' });
    await expect(
      result.current.mutateAsync({ playlistId: 'p1', file: gif }),
    ).rejects.toThrow(/unsupported/i);
  });
});
