import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { ArtistDetail } from '../../../api/artists';

export const artistDetailKey = (id: string | null) => ['library', 'artistDetail', id] as const;

export function useArtistDetail(artistId: string | null) {
  return useQuery<ArtistDetail, Error>({
    queryKey: artistDetailKey(artistId),
    queryFn: () => api<ArtistDetail>(`/artists/${artistId}`),
    enabled: !!artistId,
    staleTime: 5 * 60_000,
  });
}
