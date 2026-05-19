import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import type { LabelDetail } from '../../../api/labels';

export const labelInfoKey = (id: string | null | undefined) => ['labelInfo', id] as const;

export function useLabelInfo(labelId: string | null | undefined) {
  return useQuery<LabelDetail, Error>({
    queryKey: labelInfoKey(labelId),
    queryFn: () => api<LabelDetail>(`/labels/${labelId}`),
    enabled: !!labelId,
    staleTime: 5 * 60_000,
    retry: (count, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return count < 1;
    },
  });
}
