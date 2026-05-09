import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface CellRun {
  run_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  item_count: number | null;
  processed_count: number | null;
  error_code: string | null;
  error_message: string | null;
  is_custom_range: boolean;
  period_start: string;
  period_end: string;
}

export function useCellRuns(args: {
  styleId: number;
  weekYear: number;
  weekNumber: number;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: ['admin', 'runs', args.styleId, args.weekYear, args.weekNumber],
    queryFn: () =>
      api<{ items: CellRun[] }>(
        `/admin/runs?style_id=${args.styleId}&week_year=${args.weekYear}&week_number=${args.weekNumber}`,
      ),
    enabled: args.enabled ?? true,
  });
}
