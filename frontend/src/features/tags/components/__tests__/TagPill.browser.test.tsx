/**
 * Browser-mode regression: 1- and 2-char tag pills share one width; longer grow.
 *
 * TagPill renders in the mono font with min-width: calc(2ch + 18px). The formula
 * accounts for the 1px border on each side (box-sizing: border-box): 2ch content
 * + 16px padding (8px × 2) + 2px border (1px × 2) = 2ch + 18px. In any monospace
 * font 1ch == one glyph, so a 1-char and a 2-char tag both clamp to the 2ch
 * min-width (equal), while a 5-char tag exceeds it (wider). This holds even if
 * the Geist Mono web font fails to load (the fallback stack is mono).
 */
import { MantineProvider } from '@mantine/core';
import { render } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { TagPill } from '../TagPill';

function widths() {
  const { container } = render(
    <MantineProvider defaultColorScheme="light">
      <TagPill name="A" color="#3b82f6" data-testid="p1" />
      <TagPill name="AB" color="#3b82f6" data-testid="p2" />
      <TagPill name="ABCDE" color="#3b82f6" data-testid="p5" />
    </MantineProvider>,
  );
  const w = (id: string) =>
    (container.querySelector(`[data-testid="${id}"]`) as HTMLElement).getBoundingClientRect()
      .width;
  return { container, w1: w('p1'), w2: w('p2'), w5: w('p5') };
}

describe('TagPill — uniform short pills (browser)', () => {
  test('1-char and 2-char pills are equal width; 5-char is wider', () => {
    const { container, w1, w2, w5 } = widths();
    expect(w1).toBeGreaterThan(0);
    // both clamp to the 2ch min-width → equal within sub-pixel rounding (±0.5px)
    expect(w1).toBeCloseTo(w2, 0);
    expect(w5).toBeGreaterThan(w2 + 1); // 5-char exceeds the min-width by ≥1px in mono

    const pill = container.querySelector('[data-testid="p1"]') as HTMLElement;
    expect(window.getComputedStyle(pill).fontFamily.toLowerCase()).toContain('mono');
  });
});
