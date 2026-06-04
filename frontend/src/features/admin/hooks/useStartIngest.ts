import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { runsTrackerStore } from '../lib/runsTracker';

export interface IngestInput {
  style_id: number;
  week_year: number;
  week_number: number;
  bp_token: string;
  period_start?: string;
  period_end?: string;
}

export interface IngestResponse {
  run_id: string;
  run_status: string;
  processing_status: string;
  is_custom_range: boolean;
}

export function useStartIngest() {
  return useMutation({
    mutationFn: (input: IngestInput) =>
      api<IngestResponse>('/admin/beatport/ingest', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: (data, vars) => {
      runsTrackerStore.getState().add({
        run_id: data.run_id,
        styleId: vars.style_id,
        weekYear: vars.week_year,
        weekNumber: vars.week_number,
        startedAt: Date.now(),
      });
    },
  });
}
