import { shiftWeek, weekOfDate, type SaturdayWeek } from '../../../lib/saturdayWeek';

/**
 * Week a new triage block should cover: the week after the one holding the
 * latest block's `date_to` (any status), or the last finished week when the
 * style has no blocks yet. Never later than the week `today` falls in.
 */
export function defaultTriageWeek(blockDateTos: string[], today: Date): SaturdayWeek {
  const current = weekOfDate(today);
  if (blockDateTos.length === 0) return shiftWeek(current, -1);
  // ISO `YYYY-MM-DD` strings sort chronologically.
  const latest = blockDateTos.reduce((a, b) => (a > b ? a : b));
  const next = shiftWeek(weekOfDate(new Date(`${latest}T00:00:00Z`)), 1);
  return next[0] > current[0] || (next[0] === current[0] && next[1] > current[1])
    ? current
    : next;
}
