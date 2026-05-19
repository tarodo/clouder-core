import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { LabelsListResponse } from '../../../api/labels';

export interface UseLabelsListParams {
  styleId: string;
  q: string;
  sort: 'name' | 'recent';
}

export const labelsListKey = (params: UseLabelsListParams) =>
  ['library', 'labels', params.styleId, params.q, params.sort] as const;

export function useLabelsList(params: UseLabelsListParams) {
  return useInfiniteQuery<LabelsListResponse, Error>({
    queryKey: labelsListKey(params),
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (params.styleId) qs.set('style', params.styleId);
      if (params.q) qs.set('q', params.q);
      qs.set('sort', params.sort);
      if (pageParam) qs.set('cursor', String(pageParam));
      return api<LabelsListResponse>(`/labels?${qs.toString()}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}
