import { describe, expect, it } from 'vitest';
import { cellState, type CoverageCell } from '../cellState';

const empty = undefined as CoverageCell | undefined;
const ok: CoverageCell = {
  week_number: 1,
  status: 'completed',
  run_id: 'r',
  item_count: 1,
  is_custom_range: false,
  period_start: '2026-01-03',
  period_end: '2026-01-09',
  started_at: '2026-01-04T09:00:00Z',
  finished_at: '2026-01-04T09:01:00Z',
};

describe('cellState', () => {
  it('empty when no cell + not running', () => {
    expect(cellState(empty, false)).toBe('empty');
  });

  it('running when active in tracker', () => {
    expect(cellState(empty, true)).toBe('running');
    expect(cellState(ok, true)).toBe('running');
  });

  it('loaded for completed standard', () => {
    expect(cellState(ok, false)).toBe('loaded');
  });

  it('loaded-custom for completed + is_custom_range', () => {
    expect(cellState({ ...ok, is_custom_range: true }, false)).toBe('loaded-custom');
  });

  it('failed for failed status', () => {
    expect(cellState({ ...ok, status: 'failed' }, false)).toBe('failed');
  });

  it('empty for unrecognised status (processing/queued are not stored by BE)', () => {
    expect(cellState({ ...ok, status: 'processing' }, false)).toBe('empty');
    expect(cellState({ ...ok, status: 'queued' }, false)).toBe('empty');
  });
});
