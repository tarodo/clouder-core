import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface CoveragePayload {
  week_year: number;
  weeks_in_year: number;
  styles: Array<{
    style_id: string;
    style_name: string;
    cells: Array<{
      week_number: number;
      status: string;
      run_id: string;
      item_count: number;
      is_custom_range: boolean;
      period_start: string;
      period_end: string;
      started_at: string;
      finished_at: string | null;
    }>;
  }>;
}

export function useCoverage(weekYear: number) {
  return useQuery({
    queryKey: ['admin', 'coverage', weekYear],
    queryFn: () => api<CoveragePayload>(`/admin/coverage?week_year=${weekYear}`),
    staleTime: 30_000,
  });
}
