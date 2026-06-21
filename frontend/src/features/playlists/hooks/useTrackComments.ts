import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { TrackCommentsResponse } from '../lib/playlistTypes';
import { trackCommentsKey } from '../lib/queryKeys';

export function useTrackComments(
  trackId: string | undefined,
  limit = 5,
): UseQueryResult<TrackCommentsResponse> {
  return useQuery({
    queryKey: trackCommentsKey(trackId ?? '', limit),
    queryFn: () =>
      api<TrackCommentsResponse>(
        `/tracks/${trackId}/comments?platform=youtube&limit=${limit}`,
      ),
    enabled: !!trackId,
  });
}
