import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { usePublishYtmusic } from './usePublishYtmusic';
import * as client from '../../../api/client';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('usePublishYtmusic', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('POSTs to publish-ytmusic with confirm_overwrite', async () => {
    const spy = vi.spyOn(client, 'api').mockResolvedValue({
      ytmusic_playlist_id: 'PLabc',
      ytmusic_url: 'https://music.youtube.com/playlist?list=PLabc',
      skipped_tracks: [],
      published_at: '2026-05-31T00:00:00Z',
    });
    const { result } = renderHook(() => usePublishYtmusic(), { wrapper });
    await result.current.mutateAsync({ playlistId: 'p1', confirmOverwrite: true });
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('/playlists/p1/publish-ytmusic', {
      method: 'POST',
      body: JSON.stringify({ confirm_overwrite: true }),
    });
  });
});
