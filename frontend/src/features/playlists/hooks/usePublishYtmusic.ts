import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { YtmusicPublishResult } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export interface PublishYtmusicInput {
  playlistId: string;
  confirmOverwrite: boolean;
}

export function usePublishYtmusic(): UseMutationResult<YtmusicPublishResult, Error, PublishYtmusicInput> {
  const qc = useQueryClient();
  return useMutation<YtmusicPublishResult, Error, PublishYtmusicInput>({
    mutationFn: ({ playlistId, confirmOverwrite }) =>
      api<YtmusicPublishResult>(`/playlists/${playlistId}/publish-ytmusic`, {
        method: 'POST',
        body: JSON.stringify({ confirm_overwrite: confirmOverwrite }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
