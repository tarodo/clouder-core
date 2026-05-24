import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistTracksKey } from '../lib/queryKeys';
import type { PaginatedPlaylistTracks, PlaylistTrackTag } from '../lib/playlistTypes';

interface AddVars { trackId: string; tag: PlaylistTrackTag }
interface RemoveVars { trackId: string; tagId: string }
interface Ctx { prev?: PaginatedPlaylistTracks }

function patch(
  data: PaginatedPlaylistTracks | undefined,
  trackId: string,
  fn: (tags: PlaylistTrackTag[]) => PlaylistTrackTag[],
): PaginatedPlaylistTracks | undefined {
  if (!data) return data;
  return {
    ...data,
    items: data.items.map((it) =>
      it.track_id === trackId ? { ...it, tags: fn(it.tags) } : it,
    ),
  };
}

export function usePlaylistAddTrackTag(playlistId: string): UseMutationResult<void, Error, AddVars, Ctx> {
  const qc = useQueryClient();
  const key = playlistTracksKey(playlistId);
  return useMutation<void, Error, AddVars, Ctx>({
    mutationFn: async ({ trackId, tag }) => {
      await api(`/tracks/${trackId}/tags`, { method: 'POST', body: JSON.stringify({ tag_id: tag.id }) });
    },
    onMutate: async ({ trackId, tag }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<PaginatedPlaylistTracks>(key);
      qc.setQueryData<PaginatedPlaylistTracks>(key, (old) =>
        patch(old, trackId, (tags) => (tags.some((t) => t.id === tag.id) ? tags : [...tags, tag])),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); },
    onSettled: () => { qc.invalidateQueries({ queryKey: key }); },
  });
}

export function usePlaylistRemoveTrackTag(playlistId: string): UseMutationResult<void, Error, RemoveVars, Ctx> {
  const qc = useQueryClient();
  const key = playlistTracksKey(playlistId);
  return useMutation<void, Error, RemoveVars, Ctx>({
    mutationFn: async ({ trackId, tagId }) => {
      await api(`/tracks/${trackId}/tags/${tagId}`, { method: 'DELETE' });
    },
    onMutate: async ({ trackId, tagId }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<PaginatedPlaylistTracks>(key);
      qc.setQueryData<PaginatedPlaylistTracks>(key, (old) =>
        patch(old, trackId, (tags) => tags.filter((t) => t.id !== tagId)),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); },
    onSettled: () => { qc.invalidateQueries({ queryKey: key }); },
  });
}
