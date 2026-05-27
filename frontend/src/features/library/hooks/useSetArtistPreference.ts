import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { artistInfoKey } from './useArtistInfo';
import { artistDetailKey } from './useArtistDetail';

export type ArtistPreference = 'liked' | 'disliked' | null;
export type PreferenceMutationStatus = 'liked' | 'disliked' | 'none';

interface Variables {
  artistId: string;
  status: PreferenceMutationStatus;
}

interface Snapshot {
  key: readonly unknown[];
  data: unknown;
}

export function useSetArtistPreference() {
  const qc = useQueryClient();
  return useMutation<void, Error, Variables, { snapshots: Snapshot[] }>({
    mutationFn: ({ artistId, status }) =>
      api<void>(`/artists/${artistId}/preference`, {
        method: 'PUT',
        body: JSON.stringify({ status }),
      }),
    onMutate: ({ artistId, status }) => {
      const next: ArtistPreference = status === 'none' ? null : status;
      const snapshots: Snapshot[] = [];

      for (const key of [artistInfoKey(artistId), artistDetailKey(artistId)]) {
        const data = qc.getQueryData(key);
        if (data !== undefined) {
          snapshots.push({ key, data });
          qc.setQueryData(key, {
            ...(data as Record<string, unknown>),
            my_preference: next,
          });
        }
      }

      const lists = qc.getQueriesData<{ items?: Array<Record<string, unknown>> }>({
        queryKey: ['library', 'artists'],
      });
      for (const [key, data] of lists) {
        if (!data || !Array.isArray(data.items)) continue;
        if (!data.items.some((it) => (it as { id?: string }).id === artistId)) continue;
        snapshots.push({ key, data });
        qc.setQueryData(key, {
          ...data,
          items: data.items.map((it) =>
            (it as { id?: string }).id === artistId ? { ...it, my_preference: next } : it,
          ),
        });
      }

      return { snapshots };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      for (const snap of ctx.snapshots) qc.setQueryData(snap.key, snap.data);
    },
    onSettled: (_data, _err, { artistId }) => {
      void qc.invalidateQueries({ queryKey: artistInfoKey(artistId) });
      void qc.invalidateQueries({ queryKey: artistDetailKey(artistId) });
      void qc.invalidateQueries({ queryKey: ['library', 'artists'] });
    },
  });
}
