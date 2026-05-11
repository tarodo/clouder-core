import { describe, expect, it } from 'vitest';
import { normalizeTagName } from '../normalizeTagName';

describe('normalizeTagName', () => {
  it('lowercases', () => {
    expect(normalizeTagName('Vocal')).toBe('vocal');
  });

  it('trims leading and trailing whitespace', () => {
    expect(normalizeTagName('  vocal  ')).toBe('vocal');
  });

  it('collapses internal whitespace runs', () => {
    expect(normalizeTagName('hard   tech')).toBe('hard tech');
    expect(normalizeTagName('hard\ttech\t\there')).toBe('hard tech here');
  });

  it('returns the empty string for empty / whitespace input', () => {
    expect(normalizeTagName('')).toBe('');
    expect(normalizeTagName('   ')).toBe('');
  });
});
