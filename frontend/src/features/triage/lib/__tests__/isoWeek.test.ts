import { describe, it, expect } from 'vitest';
import { isoWeekOf } from '../isoWeek';

describe('isoWeekOf', () => {
  it('returns ISO week 17 for 2026-04-20 (a Monday)', () => {
    expect(isoWeekOf(new Date('2026-04-20T00:00:00Z'))).toBe(17);
  });

  it('returns ISO week 1 for 2026-01-01 (a Thursday)', () => {
    expect(isoWeekOf(new Date('2026-01-01T00:00:00Z'))).toBe(1);
  });

  it('returns ISO week 1 for 2025-12-29 (Monday belongs to ISO week 1 of 2026)', () => {
    expect(isoWeekOf(new Date('2025-12-29T00:00:00Z'))).toBe(1);
  });

  it('returns ISO week 1 for 2024-12-30 (Monday belongs to ISO week 1 of 2025)', () => {
    expect(isoWeekOf(new Date('2024-12-30T00:00:00Z'))).toBe(1);
  });

  it('returns ISO week 53 for 2020-12-31 (Thursday in a 53-week year)', () => {
    expect(isoWeekOf(new Date('2020-12-31T00:00:00Z'))).toBe(53);
  });
});
