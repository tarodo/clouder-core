import { describe, it, expect } from 'vitest';
import { weekLabel } from '../weekLabel';

describe('weekLabel', () => {
  it('formats a mid-year ISO date as YYYY-Www', () => {
    expect(weekLabel('2026-05-04')).toBe('2026-W19');
  });
  it('handles ISO week-1 (Jan 5 2026 is W02)', () => {
    expect(weekLabel('2026-01-05')).toBe('2026-W02');
  });
  it('handles year boundary (Dec 29 2025 is 2026-W01)', () => {
    expect(weekLabel('2025-12-29')).toBe('2026-W01');
  });
  it('returns empty string for an invalid input', () => {
    expect(weekLabel('not-a-date')).toBe('');
  });
});
