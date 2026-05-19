import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { labelInfoKey } from './useLabelInfo';

export type LabelPreference = 'liked' | 'disliked' | null;
export type PreferenceMutationStatus = 'liked' | 'disliked' | 'none';

interface Variables {
  labelId: string;
  status: PreferenceMutationStatus;
}

interface InfoSnapshot {
  key: readonly unknown[];
  data: unknown;
}

export function useSetLabelPreference() {
  const qc = useQueryClient();
  return useMutation<void, Error, Variables, { snapshots: InfoSnapshot[] }>({
    mutationFn: ({ labelId, status }) =>
      api<void>(`/labels/${labelId}/preference`, {
        method: 'PUT',
        body: JSON.stringify({ status }),
      }),
    onMutate: ({ labelId, status }) => {
      const next: LabelPreference = status === 'none' ? null : status;
      const snapshots: InfoSnapshot[] = [];

      // labelInfo: single keyed query.
      const infoKey = labelInfoKey(labelId);
      const infoData = qc.getQueryData(infoKey);
      if (infoData !== undefined) {
        snapshots.push({ key: infoKey, data: infoData });
        qc.setQueryData(infoKey, {
          ...(infoData as Record<string, unknown>),
          my_preference: next,
        });
      }

      // labelsList: many queries — patch the matching row in each.
      const listEntries = qc.getQueriesData<{ items?: Array<Record<string, unknown>> }>({
        queryKey: ['library', 'labels'],
      });
      for (const [key, data] of listEntries) {
        if (!data || !Array.isArray(data.items)) continue;
        const hit = data.items.some((it) => (it as { id?: string }).id === labelId);
        if (!hit) continue;
        snapshots.push({ key, data });
        qc.setQueryData(key, {
          ...data,
          items: data.items.map((it) =>
            (it as { id?: string }).id === labelId
              ? { ...it, my_preference: next }
              : it,
          ),
        });
      }

      return { snapshots };
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return;
      for (const snap of ctx.snapshots) {
        qc.setQueryData(snap.key, snap.data);
      }
    },
    onSettled: (_data, _err, { labelId }) => {
      void qc.invalidateQueries({ queryKey: labelInfoKey(labelId) });
    },
  });
}
