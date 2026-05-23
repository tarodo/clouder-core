/**
 * Fixed user-tag colour palette. Designed to read on both light and dark
 * Mantine themes; muted enough to coexist with category UI accents.
 */
export const TAG_PALETTE = [
  '#ef4444', // red
  '#f97316', // orange
  '#eab308', // yellow
  '#22c55e', // green
  '#14b8a6', // teal
  '#06b6d4', // cyan
  '#3b82f6', // blue
  '#8b5cf6', // violet
  '#d946ef', // fuchsia
  '#ec4899', // pink
  '#78716c', // stone (neutral warm)
  '#0f172a', // slate (neutral dark)
] as const;

export type TagPaletteColor = (typeof TAG_PALETTE)[number];

export function isPaletteColor(value: string | null | undefined): value is TagPaletteColor {
  if (typeof value !== 'string') return false;
  const lower = value.toLowerCase();
  return TAG_PALETTE.some((c) => c.toLowerCase() === lower);
}

/**
 * Returns the foreground colour to use on top of the supplied background.
 * Uses the WCAG relative-luminance formula and a 0.5 threshold; matches
 * the contrast feel users expect from Mantine `Badge`.
 */
export function pickPillTextColor(bg: string | null | undefined): string {
  if (!bg) return 'var(--mantine-color-text)';
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(bg);
  if (!m) return 'var(--mantine-color-text)';
  const channel = (c: number) =>
    c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  const r = channel(parseInt(m[1]!, 16) / 255);
  const g = channel(parseInt(m[2]!, 16) / 255);
  const b = channel(parseInt(m[3]!, 16) / 255);
  const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return L > 0.5 ? '#000000' : '#ffffff';
}

export interface SoftTagColors {
  /** Low-alpha tint for the pill background. */
  bg: string;
  /** Darkened, readable foreground text colour. */
  fg: string;
  /** Subtle hairline border colour. */
  border: string;
}

const NEUTRAL_SOFT: SoftTagColors = {
  bg: 'rgba(100, 116, 139, 0.12)',
  fg: '#475569',
  border: 'rgba(100, 116, 139, 0.3)',
};

/**
 * Derives a soft "label" treatment from a stored tag colour: a light tint
 * background, a darkened readable text colour, and a subtle border. Computed
 * client-side so existing tags soften without any data migration.
 */
export function softTagColors(hex: string | null | undefined): SoftTagColors {
  const m =
    typeof hex === 'string'
      ? /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
      : null;
  if (!m) return NEUTRAL_SOFT;
  const r = parseInt(m[1]!, 16);
  const g = parseInt(m[2]!, 16);
  const b = parseInt(m[3]!, 16);
  const darken = (c: number) =>
    Math.round(c * 0.55)
      .toString(16)
      .padStart(2, '0');
  return {
    bg: `rgba(${r}, ${g}, ${b}, 0.13)`,
    fg: `#${darken(r)}${darken(g)}${darken(b)}`,
    border: `rgba(${r}, ${g}, ${b}, 0.3)`,
  };
}
