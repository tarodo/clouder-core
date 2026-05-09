import { describe, expect, it } from 'vitest';
import {
  firstSaturday,
  saturdayWeekRange,
  weekOfDate,
  weeksInYear,
} from './saturdayWeek';

describe('saturdayWeek', () => {
  it('firstSaturday(2026) = 2026-01-03', () => {
    expect(firstSaturday(2026).toISOString().slice(0, 10)).toBe('2026-01-03');
  });

  it('firstSaturday(2028) = 2028-01-01 (Jan 1 itself is Saturday)', () => {
    expect(firstSaturday(2028).toISOString().slice(0, 10)).toBe('2028-01-01');
  });

  it('saturdayWeekRange(2026,1) = 2026-01-03..2026-01-09', () => {
    const [s, e] = saturdayWeekRange(2026, 1);
    expect(s.toISOString().slice(0, 10)).toBe('2026-01-03');
    expect(e.toISOString().slice(0, 10)).toBe('2026-01-09');
  });

  it('weeksInYear(2026) = 52', () => {
    expect(weeksInYear(2026)).toBe(52);
  });

  it('weeksInYear(2028) = 53', () => {
    expect(weeksInYear(2028)).toBe(53);
  });

  it('weekOfDate(2027-01-01) = (2026,52) — falls before first Saturday of 2027', () => {
    expect(weekOfDate(new Date(Date.UTC(2027, 0, 1)))).toEqual([2026, 52]);
  });

  it('saturdayWeekRange round-trips with weekOfDate for all weeks of 2026', () => {
    for (let n = 1; n <= weeksInYear(2026); n += 1) {
      const [start] = saturdayWeekRange(2026, n);
      expect(weekOfDate(start)).toEqual([2026, n]);
    }
  });

  it('saturdayWeekRange throws on out-of-range', () => {
    expect(() => saturdayWeekRange(2026, 0)).toThrow();
    expect(() => saturdayWeekRange(2026, weeksInYear(2026) + 1)).toThrow();
  });
});
