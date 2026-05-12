import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';
import type { CreatePlaylistInput } from '../lib/playlistSchemas';

export function useCreatePlaylist(): UseMutationResult<Playlist, Error, CreatePlaylistInput> {
  const qc = useQueryClient();
  return useMutation<Playlist, Error, CreatePlaylistInput>({
    mutationFn: (input) =>
      api<Playlist>('/playlists', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
