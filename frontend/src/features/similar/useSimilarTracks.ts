import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { paths } from '../../api/schema';
import type { EntityTrack, EntityTracksPage } from '../library/hooks/useEntityTracks';

type TrackSimilar =
  paths['/tracks/{track_id}/similar']['get']['responses'][200]['content']['application/json'];
type ArtistSimilar =
  paths['/artists/{artist_id}/similar']['get']['responses'][200]['content']['application/json'];

/** One page in the entity list's shape (so patchEntityTrack reaches it), plus the response. */
export type SimilarTrackPage = EntityTracksPage & Omit<TrackSimilar, 'items'>;
export type ArtistSimilarPage = EntityTracksPage & Omit<ArtistSimilar, 'items'>;

// Under the entity lists' key: a category / playlist toggle patches these rows too.
export const similarTrackKey = (trackId: string) =>
  ['library', 'entityTracks', 'similar', 'track', trackId] as const;
export const artistSimilarKey = (artistId: string, styleId: string | null) =>
  ['library', 'entityTracks', 'similar', 'artist', artistId, styleId] as const;

const page = (items: EntityTrack[]) => ({ items, total: items.length, limit: 50, offset: 0 });

/** The seed (first, marked) and the tracks that sound like it; one page, no "more". */
export function useSimilarTracks(trackId: string) {
  return useInfiniteQuery({
    queryKey: similarTrackKey(trackId),
    queryFn: async (): Promise<SimilarTrackPage> => {
      const body = await api<TrackSimilar>(`/tracks/${trackId}/similar`);
      // the seed alone is no list: the page says nothing similar was found
      const seed = body.seed && body.items.length > 0 ? [{ ...body.seed, seed: true }] : [];
      return { ...body, ...page([...seed, ...body.items]) };
    },
    initialPageParam: 0,
    getNextPageParam: () => undefined,
  });
}

/** The tracks nearest the artist's sound in *styleId* (null: the artist's main style). */
export function useArtistSimilar(artistId: string, styleId: string | null) {
  return useInfiniteQuery({
    queryKey: artistSimilarKey(artistId, styleId),
    queryFn: async (): Promise<ArtistSimilarPage> => {
      const q = styleId ? `?style_id=${encodeURIComponent(styleId)}` : '';
      const body = await api<ArtistSimilar>(`/artists/${artistId}/similar${q}`);
      return { ...body, ...page(body.items) };
    },
    initialPageParam: 0,
    getNextPageParam: () => undefined,
  });
}
