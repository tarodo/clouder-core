import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedPlaylistTracks } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';

export interface RemoveTrackInput {
  playlistId: string;
  trackId: string;
}

interface RollbackCtx {
  previousTracks?: PaginatedPlaylistTracks;
}

export function useRemoveTrackFromPlaylist(): UseMutationResult<
  void,
  Error,
  RemoveTrackInput,
  RollbackCtx
> {
  const qc = useQueryClient();
  return useMutation<void, Error, RemoveTrackInput, RollbackCtx>({
    mutationFn: async ({ playlistId, trackId }) => {
      await api<void>(`/playlists/${playlistId}/tracks/${trackId}`, { method: 'DELETE' });
    },
    onMutate: async ({ playlistId, trackId }) => {
      await qc.cancelQueries({ queryKey: playlistTracksKey(playlistId) });
      const previousTracks = qc.getQueryData<PaginatedPlaylistTracks>(
        playlistTracksKey(playlistId),
      );
      if (previousTracks) {
        qc.setQueryData<PaginatedPlaylistTracks>(playlistTracksKey(playlistId), {
          ...previousTracks,
          items: previousTracks.items.filter((t) => t.track_id !== trackId),
          total: Math.max(0, previousTracks.total - 1),
        });
      }
      return { previousTracks };
    },
    onError: (_err, { playlistId }, ctx) => {
      if (ctx?.previousTracks) {
        qc.setQueryData(playlistTracksKey(playlistId), ctx.previousTracks);
      }
    },
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      // Removing from a playlist may flip used_in_playlist back to false on
      // category-tracks views, but only if no OTHER playlist still holds the
      // track. We cannot compute that locally, so invalidate.
      qc.invalidateQueries({ queryKey: ['categories', 'tracks'] });
    },
  });
}
