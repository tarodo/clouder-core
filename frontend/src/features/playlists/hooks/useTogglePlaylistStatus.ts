import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Playlist, PlaylistStatus } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export interface ToggleStatusInput {
  playlistId: string;
  status: PlaylistStatus;
}

// Standalone mutation (not parameterised by id like usePatchPlaylist) so
// list rows can each fire it without proliferating per-row hooks.
export function useTogglePlaylistStatus(): UseMutationResult<Playlist, Error, ToggleStatusInput> {
  const qc = useQueryClient();
  return useMutation<Playlist, Error, ToggleStatusInput>({
    mutationFn: ({ playlistId, status }) =>
      api<Playlist>(`/playlists/${playlistId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      }),
    onSuccess: (data) => {
      qc.setQueryData(playlistDetailKey(data.id), data);
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
