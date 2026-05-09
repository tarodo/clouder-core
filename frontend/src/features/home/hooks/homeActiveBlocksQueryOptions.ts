import { queryOptions } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type {
  TriageBlockSummary,
  PaginatedTriageBlocks,
} from '../../triage/hooks/useTriageBlocksByStyle';

const PAGE_LIMIT = 50;

export function homeActiveBlocksKey(styleId: string) {
  return ['home', 'activeBlocks', styleId] as const;
}

export function homeActiveBlocksQueryOptions(styleId: string) {
  return queryOptions({
    queryKey: homeActiveBlocksKey(styleId),
    queryFn: async (): Promise<TriageBlockSummary[]> => {
      const params = new URLSearchParams({
        status: 'IN_PROGRESS',
        limit: String(PAGE_LIMIT),
        offset: '0',
      });
      const page = await api<PaginatedTriageBlocks>(
        `/styles/${styleId}/triage/blocks?${params.toString()}`,
      );
      return page.items;
    },
    enabled: !!styleId,
    staleTime: 30_000,
  });
}
