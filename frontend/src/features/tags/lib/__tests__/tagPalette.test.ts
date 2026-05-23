import { describe, expect, it } from 'vitest';
import { TAG_PALETTE, pickPillTextColor, isPaletteColor, softTagColors } from '../tagPalette';

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

describe('softTagColors', () => {
  it('produces a soft tint from a hex colour', () => {
    const sc = softTagColors('#ef4444');
    expect(sc.bg).toBe('rgba(239, 68, 68, 0.13)');
    expect(sc.border).toBe('rgba(239, 68, 68, 0.3)');
    // fg = each channel * 0.55, rounded: 131,37,37
    expect(sc.fg).toBe('#832525');
  });

  it('returns a neutral grey tint for null/invalid colour', () => {
    const neutral = {
      bg: 'rgba(100, 116, 139, 0.12)',
      fg: '#475569',
      border: 'rgba(100, 116, 139, 0.3)',
    };
    expect(softTagColors(null)).toEqual(neutral);
    expect(softTagColors('not-a-hex')).toEqual(neutral);
  });

  it('keeps very dark colours as dark text on a light tint', () => {
    const sc = softTagColors('#0f172a');
    expect(sc.bg).toBe('rgba(15, 23, 42, 0.13)');
    expect(sc.fg).toBe('#080d17'); // 15*.55=8, 23*.55=13, 42*.55=23
  });
});
