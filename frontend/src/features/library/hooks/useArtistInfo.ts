import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import type { ArtistDetail } from '../../../api/artists';

export const artistInfoKey = (id: string | null | undefined) => ['artistInfo', id] as const;

export function useArtistInfo(artistId: string | null | undefined) {
  return useQuery<ArtistDetail, Error>({
    queryKey: artistInfoKey(artistId),
    queryFn: () => api<ArtistDetail>(`/artists/${artistId}`),
    enabled: !!artistId,
    staleTime: 5 * 60_000,
    retry: (count, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return count < 1;
    },
  });
}
