import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistDetailKey } from '../lib/queryKeys';

export function useDeletePlaylist(): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (id) => {
      await api<void>(`/playlists/${id}`, { method: 'DELETE' });
    },
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: playlistDetailKey(id) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
