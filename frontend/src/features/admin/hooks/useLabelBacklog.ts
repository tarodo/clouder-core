import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { BacklogResponse } from '../../../api/labels';

export type LabelStatusFilter = 'all' | 'none' | 'completed' | 'outdated';

export interface UseLabelBacklogParams {
  style: string;
  status: LabelStatusFilter;
}

export const labelBacklogKey = (p: UseLabelBacklogParams) =>
  ['admin', 'labelBacklog', p.style, p.status] as const;

export function useLabelBacklog(p: UseLabelBacklogParams) {
  return useInfiniteQuery<BacklogResponse, Error>({
    queryKey: labelBacklogKey(p),
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (p.style) qs.set('style', p.style);
      if (p.status !== 'all') qs.set('status', p.status);
      qs.set('limit', '100');
      if (pageParam) qs.set('cursor', String(pageParam));
      return api<BacklogResponse>(`/admin/labels/backlog?${qs.toString()}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}
