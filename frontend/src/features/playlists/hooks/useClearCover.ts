import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistDetailKey } from '../lib/queryKeys';

export function useClearCover(): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (playlistId) => {
      await api<void>(`/playlists/${playlistId}/cover`, { method: 'DELETE' });
    },
    onSuccess: (_data, playlistId) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
