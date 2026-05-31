import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistTracksKey } from '../lib/queryKeys';
import type {
  PaginatedPlaylistTracks, ResolveMatchVars, YtMusicMatch,
} from '../lib/playlistTypes';

interface ResolveResponse { ytmusic: YtMusicMatch | null }
interface Ctx { prev?: PaginatedPlaylistTracks }

function setStatus(
  data: PaginatedPlaylistTracks | undefined,
  trackId: string,
  ytmusic: YtMusicMatch,
): PaginatedPlaylistTracks | undefined {
  if (!data) return data;
  return {
    ...data,
    items: data.items.map((it) => (it.track_id === trackId ? { ...it, ytmusic } : it)),
  };
}

export function useResolveMatch(
  playlistId: string,
  trackId: string,
): UseMutationResult<ResolveResponse, Error, ResolveMatchVars, Ctx> {
  const qc = useQueryClient();
  const key = playlistTracksKey(playlistId);
  return useMutation<ResolveResponse, Error, ResolveMatchVars, Ctx>({
    mutationFn: (vars) => {
      const body =
        vars.action === 'accept'
          ? { vendor: 'ytmusic', action: 'accept', vendor_track_id: vars.vendorTrackId }
          : { vendor: 'ytmusic', action: 'reject' };
      return api<ResolveResponse>(
        `/playlists/${playlistId}/tracks/${trackId}/match-resolve`,
        { method: 'POST', body: JSON.stringify(body) },
      );
    },
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<PaginatedPlaylistTracks>(key);
      const optimistic: YtMusicMatch =
        vars.action === 'accept'
          ? { status: 'matched', video_id: vars.vendorTrackId,
              url: `https://music.youtube.com/watch?v=${vars.vendorTrackId}` }
          : { status: 'not_found' };
      qc.setQueryData<PaginatedPlaylistTracks>(key, (old) => setStatus(old, trackId, optimistic));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); },
    onSuccess: (data) => {
      if (data?.ytmusic) {
        qc.setQueryData<PaginatedPlaylistTracks>(key, (old) =>
          setStatus(old, trackId, data.ytmusic!));
      }
    },
    onSettled: () => { qc.invalidateQueries({ queryKey: key }); },
  });
}
