import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { ImportSpotifyResult } from '../lib/playlistTypes';
import { playlistDetailKey, playlistTracksKey } from '../lib/queryKeys';

export interface ImportSpotifyInput {
  playlistId: string;
  spotifyRefs: string[];
}

export function useImportSpotifyTracks(): UseMutationResult<
  ImportSpotifyResult,
  Error,
  ImportSpotifyInput
> {
  const qc = useQueryClient();
  return useMutation<ImportSpotifyResult, Error, ImportSpotifyInput>({
    mutationFn: ({ playlistId, spotifyRefs }) =>
      api<ImportSpotifyResult>(`/playlists/${playlistId}/tracks/import-spotify`, {
        method: 'POST',
        body: JSON.stringify({ spotify_refs: spotifyRefs }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: playlistTracksKey(playlistId) });
    },
  });
}
