import { describe, expect, it } from 'vitest';
import { barHeights, decodeWaveform } from '../waveform';

/** wave-1 bytes: low band, then mid, then high, each `n` bins. */
function encode(low: number[], mid: number[], high = low.map(() => 0)): string {
  return btoa(String.fromCharCode(...low, ...mid, ...high));
}

describe('decodeWaveform', () => {
  it('mixes 3/4 bass with 1/4 mids and stretches the track over 0..1', () => {
    const n = 20;
    const low = Array.from({ length: n }, (_, i) => (i < 10 ? 40 : 240));
    const mid = Array.from({ length: n }, () => 100);
    const loud = decodeWaveform(encode(low, mid));
    expect(loud).toHaveLength(n);
    // quietest 5% sits at the bottom, the loudest moment at the top
    expect(loud[0]).toBe(0);
    expect(loud[n - 1]).toBe(1);
  });

  it('ignores the high band', () => {
    const low = [10, 200, 10, 200];
    const mid = [50, 50, 50, 50];
    expect(decodeWaveform(encode(low, mid, [255, 0, 255, 0]))).toEqual(
      decodeWaveform(encode(low, mid, [0, 255, 0, 255])),
    );
  });

  it('keeps a flat track flat instead of dividing by zero', () => {
    const loud = decodeWaveform(encode([128, 128, 128], [128, 128, 128]));
    expect(loud.every((v) => Number.isFinite(v))).toBe(true);
  });
});

describe('barHeights', () => {
  it('gives each bar the loudest bin under it, with dips deepened', () => {
    const heights = barHeights([0, 1, 0, 0, 0.5, 0], 3);
    expect(heights).toHaveLength(3);
    expect(heights[0]).toBe(100); // max(0, 1)
    expect(heights[1]).toBe(10); // silence keeps a 10% stub
    expect(heights[2]).toBeCloseTo(10 + 90 * 0.5 ** 1.6);
  });

  it('spreads few bins over many bars', () => {
    expect(barHeights([0, 1], 4)).toEqual([10, 10, 100, 100]);
  });
});
