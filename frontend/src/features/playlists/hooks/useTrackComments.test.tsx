import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useTrackComments } from './useTrackComments';
import * as client from '../../../api/client';
import type { TrackCommentsResponse } from '../lib/playlistTypes';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const RESP: TrackCommentsResponse = {
  status: 'collected',
  comment_count: 1,
  video_url: 'https://youtube.com/watch?v=v',
  comments: [
    { author_name: 'A', author_avatar_url: null, text: 'hi', like_count: 2, published_at: null },
  ],
};

describe('useTrackComments', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches comments for a track', async () => {
    const spy = vi.spyOn(client, 'api').mockResolvedValue(RESP);
    const { result } = renderHook(() => useTrackComments('t1', 5), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.comments[0]?.author_name).toBe('A');
    expect(spy).toHaveBeenCalledWith('/tracks/t1/comments?platform=youtube&limit=5');
  });

  it('is disabled without a track id', () => {
    const spy = vi.spyOn(client, 'api').mockResolvedValue(RESP);
    renderHook(() => useTrackComments(undefined, 5), { wrapper });
    expect(spy).not.toHaveBeenCalled();
  });
});
