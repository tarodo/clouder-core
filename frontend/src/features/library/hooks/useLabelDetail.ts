import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { LabelDetail } from '../../../api/labels';

export const labelDetailKey = (id: string | null) => ['library', 'labelDetail', id] as const;

export function useLabelDetail(labelId: string | null) {
  return useQuery<LabelDetail, Error>({
    queryKey: labelDetailKey(labelId),
    queryFn: () => api<LabelDetail>(`/labels/${labelId}`),
    enabled: !!labelId,
    staleTime: 5 * 60_000,
  });
}
