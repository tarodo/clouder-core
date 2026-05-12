import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';
import type { PatchPlaylistInput } from '../lib/playlistSchemas';
import { playlistDetailKey } from '../lib/queryKeys';

export function usePatchPlaylist(
  id: string,
): UseMutationResult<Playlist, Error, PatchPlaylistInput, { previous?: Playlist }> {
  const qc = useQueryClient();
  return useMutation<Playlist, Error, PatchPlaylistInput, { previous?: Playlist }>({
    mutationFn: (input) =>
      api<Playlist>(`/playlists/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: playlistDetailKey(id) });
      const previous = qc.getQueryData<Playlist>(playlistDetailKey(id));
      if (previous) {
        qc.setQueryData<Playlist>(playlistDetailKey(id), {
          ...previous,
          ...('name' in input && input.name !== undefined ? { name: input.name } : {}),
          ...('description' in input ? { description: input.description ?? null } : {}),
          ...('is_public' in input && input.is_public !== undefined
            ? { is_public: input.is_public }
            : {}),
          ...('status' in input && input.status !== undefined
            ? { status: input.status }
            : {}),
        });
      }
      return { previous };
    },
    onError: (_err, _input, ctx) => {
      if (ctx?.previous) qc.setQueryData(playlistDetailKey(id), ctx.previous);
    },
    onSuccess: (data) => {
      qc.setQueryData(playlistDetailKey(id), data);
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
