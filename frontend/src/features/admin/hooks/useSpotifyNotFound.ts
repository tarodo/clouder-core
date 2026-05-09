import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface SpotifyNotFoundItem {
  track_id: string;
  title: string;
  artists: string[];
  album?: string | null;
  label?: string | null;
  style?: string | null;
  isrc?: string | null;
  last_seen_at?: string | null;
}

export function useSpotifyNotFound(args: {
  limit: number;
  offset: number;
  search: string;
}) {
  const params = new URLSearchParams({
    limit: String(args.limit),
    offset: String(args.offset),
  });
  if (args.search) params.set('search', args.search);
  return useQuery({
    queryKey: ['admin', 'spotifyNotFound', args.limit, args.offset, args.search],
    queryFn: () =>
      api<{ items: SpotifyNotFoundItem[]; total: number; limit: number; offset: number }>(
        `/tracks/spotify-not-found?${params.toString()}`,
      ),
    placeholderData: keepPreviousData,
  });
}
