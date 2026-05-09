import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { runsTrackerStore } from '../lib/runsTracker';

interface RunPayload {
  run_id: string;
  status: string;
}

const TERMINAL = new Set(['completed', 'failed']);

export function useRunPoller(
  run_id: string | null,
  args: { styleId: number; weekYear: number; weekNumber: number } | null,
) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['runs', run_id],
    queryFn: () => api<RunPayload>(`/runs/${run_id}`),
    enabled: !!run_id,
    refetchInterval: (q) => {
      const data = q.state.data as RunPayload | undefined;
      if (!data) return 2000;
      return TERMINAL.has(data.status.toLowerCase()) ? false : 2000;
    },
  });

  useEffect(() => {
    if (!query.data || !run_id || !args) return;
    if (!TERMINAL.has(query.data.status.toLowerCase())) return;
    runsTrackerStore.getState().remove(run_id);
    void qc.invalidateQueries({ queryKey: ['admin', 'coverage', args.weekYear] });
    void qc.invalidateQueries({
      queryKey: ['admin', 'runs', args.styleId, args.weekYear, args.weekNumber],
    });
  }, [query.data, run_id, args, qc]);

  return query;
}
