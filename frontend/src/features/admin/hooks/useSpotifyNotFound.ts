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
  publishDateFrom?: string | null;
  publishDateTo?: string | null;
}) {
  const params = new URLSearchParams({
    limit: String(args.limit),
    offset: String(args.offset),
  });
  if (args.search) params.set('search', args.search);
  if (args.publishDateFrom) params.set('publish_date_from', args.publishDateFrom);
  if (args.publishDateTo) params.set('publish_date_to', args.publishDateTo);
  return useQuery({
    queryKey: [
      'admin',
      'spotifyNotFound',
      args.limit,
      args.offset,
      args.search,
      args.publishDateFrom ?? null,
      args.publishDateTo ?? null,
    ],
    queryFn: () =>
      api<{ items: SpotifyNotFoundItem[]; total: number; limit: number; offset: number }>(
        `/tracks/spotify-not-found?${params.toString()}`,
      ),
    placeholderData: keepPreviousData,
  });
}
