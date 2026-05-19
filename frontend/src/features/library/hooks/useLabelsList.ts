import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { LabelsListResponse } from '../../../api/labels';

export interface UseLabelsListParams {
  styleId: string;
  q: string;
  sort: 'name' | 'recent';
  page: number;
  limit: number;
}

export const labelsListKey = (params: UseLabelsListParams) =>
  [
    'library',
    'labels',
    params.styleId,
    params.q,
    params.sort,
    params.page,
    params.limit,
  ] as const;

export function useLabelsList(params: UseLabelsListParams) {
  return useQuery<LabelsListResponse, Error>({
    queryKey: labelsListKey(params),
    queryFn: () => {
      const qs = new URLSearchParams();
      if (params.styleId) qs.set('style', params.styleId);
      if (params.q) qs.set('q', params.q);
      qs.set('sort', params.sort);
      qs.set('page', String(params.page));
      qs.set('limit', String(params.limit));
      return api<LabelsListResponse>(`/labels?${qs.toString()}`);
    },
    placeholderData: (prev) => prev,
  });
}
