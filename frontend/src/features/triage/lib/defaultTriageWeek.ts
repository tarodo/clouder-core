import {
  saturdayWeekRange,
  shiftWeek,
  weekOfDate,
  type SaturdayWeek,
} from '../../../lib/saturdayWeek';

const DAY_MS = 86_400_000;

const startOf = ([year, week]: SaturdayWeek) => saturdayWeekRange(year, week)[0].getTime();

/**
 * Week a new triage block should cover: the first one starting after the
 * latest block's `date_to` (any status), or the last finished week when the style has no
 * blocks yet. Never later than the week `today` falls in.
 */
export function defaultTriageWeek(blockDateTos: string[], today: Date): SaturdayWeek {
  const current = weekOfDate(today);
  if (blockDateTos.length === 0) return shiftWeek(current, -1);
  // ISO `YYYY-MM-DD` strings sort chronologically.
  const latest = blockDateTos.reduce((a, b) => (a > b ? a : b));
  const latestMs = Date.parse(`${latest}T00:00:00Z`);
  let next = weekOfDate(new Date(latestMs + DAY_MS));
  // A custom range ending mid-week has started that week: take the next one.
  if (startOf(next) <= latestMs) next = shiftWeek(next, 1);
  return startOf(next) > startOf(current) ? current : next;
}
