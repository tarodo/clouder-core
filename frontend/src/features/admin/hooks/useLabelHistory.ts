import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { LabelHistoryResponse } from '../../../api/labels';

export function useLabelHistory(labelId: string | null) {
  return useQuery<LabelHistoryResponse, Error>({
    queryKey: ['admin', 'labelHistory', labelId] as const,
    queryFn: () => api<LabelHistoryResponse>(`/admin/labels/${labelId}/history`),
    enabled: !!labelId,
    staleTime: 30_000,
  });
}
