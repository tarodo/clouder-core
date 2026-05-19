import { describe, it, expect } from 'vitest';
import { countryFlag } from '../countryFlag';

describe('countryFlag', () => {
  it('emits the regional-indicator emoji for ISO-2', () => {
    expect(countryFlag('NL')).toBe('🇳🇱');
    expect(countryFlag('us')).toBe('🇺🇸');
  });
  it('returns empty string for invalid input', () => {
    expect(countryFlag(null)).toBe('');
    expect(countryFlag('XX1')).toBe('');
  });
});
