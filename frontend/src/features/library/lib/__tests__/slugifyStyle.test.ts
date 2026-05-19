import { describe, it, expect } from 'vitest';
import { slugifyStyle } from '../slugifyStyle';

describe('slugifyStyle', () => {
  it('maps "Drum & Bass" to "drum-and-bass"', () => {
    expect(slugifyStyle('Drum & Bass')).toBe('drum-and-bass');
  });
  it('maps "Melodic House & Techno" to "melodic-house-and-techno"', () => {
    expect(slugifyStyle('Melodic House & Techno')).toBe('melodic-house-and-techno');
  });
  it('strips parens and slashes', () => {
    expect(slugifyStyle('Techno (Peak Time / Driving)')).toBe('techno-peak-time-driving');
  });
  it('lowercases plain names', () => {
    expect(slugifyStyle('House')).toBe('house');
  });
});
