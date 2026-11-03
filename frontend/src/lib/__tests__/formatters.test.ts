import { describe, it, expect } from 'vitest';
import { formatLength, formatAdded, formatReleaseDate, formatCommentCount } from '../formatters';

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
  it('returns the local calendar date as YYYY-MM-DD, like a release date', () => {
    expect(formatAdded('2026-04-15T12:00:00Z')).toBe('2026-04-15');
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

describe('formatCommentCount', () => {
  it('shows the count, 100 (a full page) as 100+, and a dash when there is none', () => {
    expect(formatCommentCount(0)).toBe('0');
    expect(formatCommentCount(12)).toBe('12');
    expect(formatCommentCount(100)).toBe('100+');
    expect(formatCommentCount(null)).toBe('—');
    expect(formatCommentCount(undefined)).toBe('—');
  });
});
