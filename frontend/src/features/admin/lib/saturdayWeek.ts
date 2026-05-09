const SATURDAY = 6; // JS getUTCDay(): Sun=0..Sat=6

function utcDate(year: number, month: number, day: number): Date {
  return new Date(Date.UTC(year, month, day));
}

export function firstSaturday(year: number): Date {
  const jan1 = utcDate(year, 0, 1);
  const delta = (SATURDAY - jan1.getUTCDay() + 7) % 7;
  return utcDate(year, 0, 1 + delta);
}

function lastSaturdayOnOrBefore(d: Date): Date {
  const delta = (d.getUTCDay() - SATURDAY + 7) % 7;
  return new Date(d.getTime() - delta * 86_400_000);
}

export function weeksInYear(year: number): number {
  const start = firstSaturday(year);
  const end = lastSaturdayOnOrBefore(utcDate(year, 11, 31));
  return Math.floor((end.getTime() - start.getTime()) / (7 * 86_400_000)) + 1;
}

export function saturdayWeekRange(year: number, week: number): [Date, Date] {
  const max = weeksInYear(year);
  if (week < 1 || week > max) {
    throw new RangeError(`week ${week} out of range for year ${year} (1..${max})`);
  }
  const start = new Date(firstSaturday(year).getTime() + (week - 1) * 7 * 86_400_000);
  const end = new Date(start.getTime() + 6 * 86_400_000);
  return [start, end];
}

export function weekOfDate(d: Date): [number, number] {
  const saturday = lastSaturdayOnOrBefore(d);
  const year = saturday.getUTCFullYear();
  const fs = firstSaturday(year);
  if (saturday.getTime() < fs.getTime()) {
    const prev = year - 1;
    const prevFs = firstSaturday(prev);
    const week = Math.floor((saturday.getTime() - prevFs.getTime()) / (7 * 86_400_000)) + 1;
    return [prev, week];
  }
  const week = Math.floor((saturday.getTime() - fs.getTime()) / (7 * 86_400_000)) + 1;
  return [year, week];
}
