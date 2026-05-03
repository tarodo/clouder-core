import { describe, it, expect } from 'vitest';
import { formatLength, formatAdded, formatReleaseDate } from '../formatters';

describe('formatLength', () => {
  it('returns m:ss for whole seconds', () => {
    expect(formatLength(135_000)).toBe('2:15');
  });
  it('rounds the seconds half-up', () => {
    expect(formatLength(59_999)).toBe('1:00');
  });
  it('returns em-dash for zero (legacy F1 behavior)', () => {
    expect(formatLength(0)).toBe('—');
  });
  it('returns em-dash for null', () => {
    expect(formatLength(null)).toBe('—');
  });
});

describe('formatAdded', () => {
  it('returns a formatted date string', () => {
    const out = formatAdded('2026-04-15T12:00:00Z');
    expect(out).toMatch(/2026/);
    expect(out).toMatch(/Apr/i);
  });
});

describe('formatReleaseDate', () => {
  it('returns the iso string verbatim', () => {
    expect(formatReleaseDate('2026-04-15')).toBe('2026-04-15');
  });
  it('returns em-dash for null', () => {
    expect(formatReleaseDate(null)).toBe('—');
  });
});
