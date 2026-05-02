import dayjs from 'dayjs';
import isoWeekPlugin from 'dayjs/plugin/isoWeek';

dayjs.extend(isoWeekPlugin);

export function isoWeekOf(date: Date): number {
  return dayjs(date).isoWeek();
}
