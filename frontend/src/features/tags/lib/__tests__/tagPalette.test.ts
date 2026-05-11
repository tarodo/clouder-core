import { describe, expect, it } from 'vitest';
import { TAG_PALETTE, pickPillTextColor, isPaletteColor } from '../tagPalette';

describe('tagPalette', () => {
  it('exposes exactly 12 unique hex colours', () => {
    expect(TAG_PALETTE).toHaveLength(12);
    const set = new Set(TAG_PALETTE.map((c) => c.toLowerCase()));
    expect(set.size).toBe(12);
    for (const c of TAG_PALETTE) {
      expect(c).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('isPaletteColor recognises members regardless of case', () => {
    expect(isPaletteColor(TAG_PALETTE[0])).toBe(true);
    expect(isPaletteColor(TAG_PALETTE[0].toUpperCase())).toBe(true);
    expect(isPaletteColor('#abcdef')).toBe(false);
    expect(isPaletteColor(null)).toBe(false);
  });

  it('pickPillTextColor returns black on light, white on dark', () => {
    expect(pickPillTextColor('#ffffff')).toBe('#000000');
    expect(pickPillTextColor('#000000')).toBe('#ffffff');
    expect(pickPillTextColor('#ffeb3b')).toBe('#000000'); // bright yellow
    expect(pickPillTextColor('#1a237e')).toBe('#ffffff'); // dark indigo
  });

  it('pickPillTextColor returns the default fg for null background', () => {
    expect(pickPillTextColor(null)).toBe('var(--mantine-color-text)');
  });
});
