import { describe, expect, it } from 'vitest';
import { defaultTriageWeek } from '../defaultTriageWeek';

// 2026-10-20 (Tue) sits in Saturday-week 42 (Oct 17–23); W41 = Oct 10–16.
const TODAY = new Date('2026-10-20T12:00:00Z');

describe('defaultTriageWeek', () => {
  it('without blocks proposes the last finished week', () => {
    expect(defaultTriageWeek([], TODAY)).toEqual([2026, 41]);
  });

  it('proposes the week after the latest block end', () => {
    expect(defaultTriageWeek(['2026-09-26', '2026-10-09', '2026-10-02'], TODAY)).toEqual([
      2026, 41,
    ]);
  });

  it('never proposes a week after the current one', () => {
    expect(defaultTriageWeek(['2026-10-23'], TODAY)).toEqual([2026, 42]);
    expect(defaultTriageWeek(['2027-03-01'], TODAY)).toEqual([2026, 42]);
  });

  it('continues a custom range that ends mid-week into the next full week', () => {
    // Oct 12 is inside W41 → next week W42.
    expect(defaultTriageWeek(['2026-10-12'], TODAY)).toEqual([2026, 42]);
  });

  it('rolls over the year boundary', () => {
    // W52 2026 = Dec 26 2026 – Jan 1 2027 → next is 2027 W1.
    expect(defaultTriageWeek(['2027-01-01'], new Date('2027-01-12T00:00:00Z'))).toEqual([
      2027, 1,
    ]);
  });
});
