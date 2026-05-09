export interface CoverageCell {
  week_number: number;
  status: string; // 'completed' | 'failed' | 'queued' | 'processing' | 'raw_saved'
  run_id: string;
  item_count: number;
  is_custom_range: boolean;
  period_start: string;
  period_end: string;
  started_at: string;
  finished_at: string | null;
}

export type CellState =
  | 'empty'
  | 'loaded'
  | 'loaded-custom'
  | 'failed'
  | 'running'
  | 'n/a';

export function cellState(
  cell: CoverageCell | undefined,
  isTrackedRunning: boolean,
): CellState {
  if (isTrackedRunning) return 'running';
  if (!cell) return 'empty';
  const status = cell.status.toLowerCase();
  if (status === 'failed') return 'failed';
  if (status === 'completed') {
    return cell.is_custom_range ? 'loaded-custom' : 'loaded';
  }
  return 'empty';
}
