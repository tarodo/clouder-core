import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { ImportSpotifyPlaylistResult } from '../lib/playlistTypes';

export interface ImportSpotifyPlaylistInput {
  spotifyRef: string;
  name?: string;
}

export function useImportSpotifyPlaylist(): UseMutationResult<
  ImportSpotifyPlaylistResult,
  Error,
  ImportSpotifyPlaylistInput
> {
  const qc = useQueryClient();
  return useMutation<ImportSpotifyPlaylistResult, Error, ImportSpotifyPlaylistInput>({
    mutationFn: ({ spotifyRef, name }) =>
      api<ImportSpotifyPlaylistResult>('/playlists/import-spotify-playlist', {
        method: 'POST',
        body: JSON.stringify({ spotify_ref: spotifyRef, ...(name ? { name } : {}) }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
