import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AddTracksResult } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';

export interface AddTracksInput {
  playlistId: string;
  trackIds: string[];
}

export function useAddTracksToPlaylist(): UseMutationResult<AddTracksResult, Error, AddTracksInput> {
  const qc = useQueryClient();
  return useMutation<AddTracksResult, Error, AddTracksInput>({
    mutationFn: ({ playlistId, trackIds }) =>
      api<AddTracksResult>(`/playlists/${playlistId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_ids: trackIds }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
    },
  });
}
