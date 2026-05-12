import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PublishResult } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export interface PublishInput {
  playlistId: string;
  confirmOverwrite: boolean;
}

export function usePublishPlaylist(): UseMutationResult<PublishResult, Error, PublishInput> {
  const qc = useQueryClient();
  return useMutation<PublishResult, Error, PublishInput>({
    mutationFn: ({ playlistId, confirmOverwrite }) =>
      api<PublishResult>(`/playlists/${playlistId}/publish`, {
        method: 'POST',
        body: JSON.stringify({ confirm_overwrite: confirmOverwrite }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
