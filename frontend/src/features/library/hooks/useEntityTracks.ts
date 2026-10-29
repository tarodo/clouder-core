import { useInfiniteQuery, type InfiniteData, type QueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { paths } from '../../../api/schema';

export type EntityKind = 'label' | 'artist';
export type EntityTracksPage =
  paths['/labels/{label_id}/tracks']['get']['responses'][200]['content']['application/json'];
export type EntityTrack = EntityTracksPage['items'][number];
export type NamedRef = EntityTrack['categories'][number];

const PAGE_SIZE = 50;

export const entityTracksKey = (kind: EntityKind, id: string) =>
  ['library', 'entityTracks', kind, id] as const;

/** A label's / an artist's tracks, newest release first, with the user's categories and playlists. */
export function useEntityTracks(kind: EntityKind, id: string) {
  return useInfiniteQuery({
    queryKey: entityTracksKey(kind, id),
    queryFn: ({ pageParam }) =>
      api<EntityTracksPage>(`/${kind}s/${id}/tracks?limit=${PAGE_SIZE}&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const next = last.offset + last.items.length;
      return last.items.length > 0 && next < last.total ? next : undefined;
    },
    enabled: !!id,
  });
}

/** Rewrites one track in every cached entity list: a category or playlist toggle shows at once. */
export function patchEntityTrack(
  qc: QueryClient,
  trackId: string,
  patch: (t: EntityTrack) => EntityTrack,
): void {
  qc.setQueriesData<InfiniteData<EntityTracksPage>>(
    { queryKey: ['library', 'entityTracks'] },
    (data) =>
      data && {
        ...data,
        pages: data.pages.map((p) => ({
          ...p,
          items: p.items.map((t) => (t.id === trackId ? patch(t) : t)),
        })),
      },
  );
}
