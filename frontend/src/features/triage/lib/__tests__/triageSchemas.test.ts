import { describe, it, expect } from 'vitest';
import {
  triageNameSchema,
  triageDateRangeSchema,
  createTriageBlockSchema,
} from '../triageSchemas';

describe('triageNameSchema', () => {
  it('accepts a normal name', () => {
    expect(triageNameSchema.safeParse('Tech House W17').success).toBe(true);
  });

  it('rejects empty / whitespace-only', () => {
    expect(triageNameSchema.safeParse('').success).toBe(false);
    expect(triageNameSchema.safeParse('   ').success).toBe(false);
  });

  it('trims surrounding whitespace before length check', () => {
    expect(triageNameSchema.safeParse('  Tech  House  ').data).toBe('Tech  House');
  });

  it('rejects 129+ chars after trim', () => {
    expect(triageNameSchema.safeParse('a'.repeat(129)).success).toBe(false);
    expect(triageNameSchema.safeParse('a'.repeat(128)).success).toBe(true);
  });

  it('rejects control characters', () => {
    expect(triageNameSchema.safeParse('A\x00B').success).toBe(false);
    expect(triageNameSchema.safeParse('A\x7fB').success).toBe(false);
  });
});

describe('triageDateRangeSchema', () => {
  it('accepts to == from', () => {
    const d = new Date('2026-04-20');
    expect(triageDateRangeSchema.safeParse([d, d]).success).toBe(true);
  });

  it('accepts to > from', () => {
    expect(
      triageDateRangeSchema.safeParse([new Date('2026-04-20'), new Date('2026-04-26')]).success,
    ).toBe(true);
  });

  it('rejects to < from', () => {
    expect(
      triageDateRangeSchema.safeParse([new Date('2026-04-26'), new Date('2026-04-20')]).success,
    ).toBe(false);
  });

  it('rejects null entries', () => {
    expect(triageDateRangeSchema.safeParse([null, null]).success).toBe(false);
  });
});

describe('createTriageBlockSchema', () => {
  it('round-trips a valid input', () => {
    const result = createTriageBlockSchema.safeParse({
      name: 'Tech House W17',
      dateRange: [new Date('2026-04-20'), new Date('2026-04-26')],
    });
    expect(result.success).toBe(true);
  });
});
