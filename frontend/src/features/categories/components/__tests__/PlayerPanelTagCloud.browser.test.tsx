/**
 * Browser-mode test: diagnose and assert the Chip focus ring is suppressed.
 *
 * Background:
 *   Three previous CSS-only attempts failed because the ring is NOT `outline`
 *   on `:focus` or `:focus-visible` of the input itself. Mantine renders the
 *   Chip as a hidden <input> + visible <label>. The focus ring is painted via
 *   the CSS adjacent-sibling rule:
 *
 *     .mantine-Chip-input:focus-visible + .mantine-Chip-label {
 *       outline: 2px solid var(--mantine-primary-color-filled);
 *       outline-offset: 2px;
 *     }
 *
 *   Applying `outline: none` to `:focus-visible` (specificity 0,1,0) cannot
 *   override the combined specificity of the input:focus-visible + label
 *   selector (specificity 0,2,0 or higher with Mantine's data-attributes).
 *
 * Repro:
 *   Click the chip (mouse) → press Space → input receives :focus-visible →
 *   label gets outline via the sibling selector.
 *
 * This test observes the computed style to confirm the ring property,
 * then asserts it is absent after the fix.
 */
import { MantineProvider, Chip } from '@mantine/core';
import { render } from '@testing-library/react';
import { userEvent } from '@vitest/browser/context';
import { describe, expect, test } from 'vitest';
import { clouderTheme } from '../../../../theme';

function renderChip() {
  return render(
    <MantineProvider theme={clouderTheme} defaultColorScheme="light">
      <Chip checked>acid</Chip>
    </MantineProvider>,
  );
}

describe('Chip focus ring — browser computed style', () => {
  test('DIAGNOSE: log computed styles on input + label after click + Space', async () => {
    const { container } = renderChip();

    const input = container.querySelector('.mantine-Chip-input') as HTMLInputElement;
    const label = container.querySelector('.mantine-Chip-label') as HTMLLabelElement;
    const root  = container.querySelector('.mantine-Chip-root') as HTMLElement;

    expect(input, 'Chip input found').not.toBeNull();
    expect(label, 'Chip label found').not.toBeNull();

    // Click the chip (simulates mouse click that leaves focus on the input)
    await userEvent.click(label);
    // Then press Space — this is the exact repro: keyboard event while focused
    // makes the browser grant :focus-visible to the input
    await userEvent.keyboard(' ');

    // ── Gather computed styles ────────────────────────────────────────────
    const csInput = window.getComputedStyle(input);
    const csLabel = window.getComputedStyle(label);
    const csRoot  = window.getComputedStyle(root ?? container.firstElementChild as HTMLElement);

    const inputStyles = {
      outline:     csInput.outline,
      outlineWidth: csInput.outlineWidth,
      boxShadow:   csInput.boxShadow,
      border:      csInput.border,
      borderColor: csInput.borderColor,
    };
    const labelStyles = {
      outline:     csLabel.outline,
      outlineWidth: csLabel.outlineWidth,
      boxShadow:   csLabel.boxShadow,
      border:      csLabel.border,
      borderColor: csLabel.borderColor,
    };
    const rootStyles = {
      outline:     csRoot.outline,
      outlineWidth: csRoot.outlineWidth,
      boxShadow:   csRoot.boxShadow,
    };

    // Log everything so the diagnosis is visible in test output
    console.warn('[CHIP-DIAGNOSIS] input computed style:', JSON.stringify(inputStyles, null, 2));
    console.warn('[CHIP-DIAGNOSIS] label computed style:', JSON.stringify(labelStyles, null, 2));
    console.warn('[CHIP-DIAGNOSIS] root computed style:', JSON.stringify(rootStyles, null, 2));

    // ── THE ASSERTION (Part D) ────────────────────────────────────────────
    // After the fix in tokens.css, the label outline-style MUST be 'none' —
    // meaning no ring is painted. The ring was:
    //   outline: 2px solid var(--mantine-primary-color-filled)
    // on the label, triggered by the sibling selector:
    //   .mantine-Chip-input:focus-visible + .mantine-Chip-label { outline: ... }
    //
    // NOTE: Chromium reports outline-width as 3px even when outline-style is
    // 'none' (browser UA default). What matters is outline-style: when it is
    // 'none', NO ring is painted regardless of the width value.
    expect(
      csLabel.outlineStyle,
      'Chip label outline-style must be none (no ring painted)',
    ).toBe('none');

    // Belt-and-suspenders: the outline shorthand must NOT contain "solid 2px"
    expect(
      csLabel.outline,
      'Chip label outline must not be the Mantine 2px solid ring',
    ).not.toMatch(/solid\s+2px|2px\s+solid/);
  });
});
