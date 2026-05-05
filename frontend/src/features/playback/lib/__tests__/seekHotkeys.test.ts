import { describe, it, expect } from 'vitest';
import { pctToMs, clampMs } from '../seekHotkeys';

describe('pctToMs', () => {
  it('converts 0.6 of 360s to 216000ms', () => {
    expect(pctToMs(0.6, 360_000)).toBe(216_000);
  });
  it('clamps fractional pct outside [0,1]', () => {
    expect(pctToMs(-0.1, 360_000)).toBe(0);
    expect(pctToMs(1.5, 360_000)).toBe(360_000);
  });
});

describe('clampMs', () => {
  it('clamps below 0 to 0', () => {
    expect(clampMs(-100, 360_000)).toBe(0);
  });
  it('clamps above duration to duration', () => {
    expect(clampMs(400_000, 360_000)).toBe(360_000);
  });
  it('passes valid values through', () => {
    expect(clampMs(150_000, 360_000)).toBe(150_000);
  });
});
