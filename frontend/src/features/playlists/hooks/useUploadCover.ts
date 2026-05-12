import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { CoverUploadUrlResponse, Playlist } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export const MAX_COVER_BYTES = 256 * 1024;
const ACCEPTED_TYPES = new Set(['image/jpeg', 'image/png']);

export interface UploadCoverInput {
  playlistId: string;
  file: File;
}

export function useUploadCover(): UseMutationResult<Playlist, Error, UploadCoverInput> {
  const qc = useQueryClient();
  return useMutation<Playlist, Error, UploadCoverInput>({
    mutationFn: async ({ playlistId, file }) => {
      if (!ACCEPTED_TYPES.has(file.type)) {
        throw new Error('unsupported_content_type');
      }
      if (file.size > MAX_COVER_BYTES) {
        throw new Error('cover_too_large');
      }
      const presign = await api<CoverUploadUrlResponse>(
        `/playlists/${playlistId}/cover/upload-url`,
        {
          method: 'POST',
          body: JSON.stringify({ content_type: file.type as 'image/jpeg' | 'image/png' }),
        },
      );
      // Presigned PUT — do not use the `api` helper because it injects
      // Authorization and credentials we must NOT send to S3.
      const putRes = await fetch(presign.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': file.type },
        body: file,
      });
      if (!putRes.ok) {
        throw new Error(`cover_put_failed_${putRes.status}`);
      }
      const playlist = await api<Playlist>(`/playlists/${playlistId}/cover/confirm`, {
        method: 'POST',
        body: JSON.stringify({ s3_key: presign.s3_key }),
      });
      return playlist;
    },
    onSuccess: (playlist) => {
      qc.setQueryData(playlistDetailKey(playlist.id), playlist);
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
