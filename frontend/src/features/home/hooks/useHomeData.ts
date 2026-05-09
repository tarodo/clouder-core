import { useQueries, useQueryClient } from '@tanstack/react-query';
import { useStyles, type Style } from '../../../hooks/useStyles';
import {
  homeActiveBlocksQueryOptions,
  homeActiveBlocksKey,
} from './homeActiveBlocksQueryOptions';
import type { TriageBlockSummary } from '../../triage/hooks/useTriageBlocksByStyle';

export interface HomeData {
  styles: Style[];
  blocksByStyle: Record<string, TriageBlockSummary[]>;
  activeBlocks: TriageBlockSummary[];
  activeBlocksCount: number;
  awaitingTriageCount: number;
  topActiveBlocks: TriageBlockSummary[];
  partialError: boolean;
}

export interface UseHomeDataResult {
  data: HomeData | undefined;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  refetchAll: () => void;
}

export function useHomeData(): UseHomeDataResult {
  const stylesQuery = useStyles();
  const qc = useQueryClient();
  const styles = stylesQuery.data?.items ?? [];

  const blockQueries = useQueries({
    queries: styles.map((s) => homeActiveBlocksQueryOptions(s.id)),
  });

  const refetchAll = () => {
    void stylesQuery.refetch();
    for (const s of styles) {
      void qc.invalidateQueries({ queryKey: homeActiveBlocksKey(s.id) });
    }
  };

  if (stylesQuery.isPending) {
    return { data: undefined, isLoading: true, isError: false, refetchAll };
  }
  if (stylesQuery.isError) {
    return { data: undefined, isLoading: false, isError: true, error: stylesQuery.error, refetchAll };
  }
  const anyPending = blockQueries.some((q) => q.isPending);
  if (anyPending) {
    return { data: undefined, isLoading: true, isError: false, refetchAll };
  }

  const blocksByStyle: Record<string, TriageBlockSummary[]> = {};
  let partialError = false;
  styles.forEach((s, idx) => {
    const q = blockQueries[idx];
    if (q?.isError) {
      partialError = true;
      blocksByStyle[s.id] = [];
    } else {
      blocksByStyle[s.id] = q?.data ?? [];
    }
  });

  const activeBlocks = Object.values(blocksByStyle)
    .flat()
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  const activeBlocksCount = activeBlocks.length;
  const awaitingTriageCount = activeBlocks.reduce((sum, b) => sum + b.track_count, 0);
  const topActiveBlocks = activeBlocks.slice(0, 5);

  return {
    data: {
      styles,
      blocksByStyle,
      activeBlocks,
      activeBlocksCount,
      awaitingTriageCount,
      topActiveBlocks,
      partialError,
    },
    isLoading: false,
    isError: false,
    refetchAll,
  };
}
