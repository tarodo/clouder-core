import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
  type InfiniteData,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AddTracksResult } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';
import type { PaginatedTracks } from '../../categories/hooks/useCategoryTracks';

export interface AddTracksInput {
  playlistId: string;
  trackIds: string[];
}

/**
 * Cache key shape from `categoryTracksKey`:
 *   ['categories', 'tracks', id, search, sort, order, tagJoin, tagMatch, fresh]
 * Index 8 holds the boolean fresh flag.
 */
function isFreshKey(key: readonly unknown[]): boolean {
  return key[0] === 'categories' && key[1] === 'tracks' && key[8] === true;
}

export function useAddTracksToPlaylist(): UseMutationResult<AddTracksResult, Error, AddTracksInput> {
  const qc = useQueryClient();
  return useMutation<AddTracksResult, Error, AddTracksInput>({
    mutationFn: ({ playlistId, trackIds }) =>
      api<AddTracksResult>(`/playlists/${playlistId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_ids: trackIds }),
      }),
    onSuccess: (_data, { playlistId, trackIds }) => {
      const trackSet = new Set(trackIds);
      // `setQueriesData` does not expose the per-query key to the updater, so
      // iterate the cache manually and call `setQueryData` per match.
      const matches = qc.getQueryCache().findAll({ queryKey: ['categories', 'tracks'] });
      for (const query of matches) {
        const key = query.queryKey;
        const fresh = isFreshKey(key);
        qc.setQueryData<InfiniteData<PaginatedTracks>>(key, (data) => {
          if (!data) return data;
          let totalRemoved = 0;
          const pages = data.pages.map((page) => {
            const before = page.items.length;
            const mapped = page.items.map((it) =>
              trackSet.has(it.id) ? { ...it, used_in_playlist: true } : it,
            );
            const filtered = fresh ? mapped.filter((it) => !trackSet.has(it.id)) : mapped;
            totalRemoved += before - filtered.length;
            return { ...page, items: filtered };
          });
          return {
            ...data,
            pages: pages.map((p, idx) =>
              idx === 0 ? { ...p, total: Math.max(0, p.total - totalRemoved) } : p,
            ),
          };
        });
      }
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
      // Refresh playlist lists (e.g. the category player's active-playlist cloud)
      // so the per-playlist track_count shown in parentheses stays current.
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
