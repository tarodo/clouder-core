/**
 * Browser-mode layout regression for the category detail header.
 *
 * Requirements:
 *  - Rename/Delete sit directly AFTER the category name (so their purpose is
 *    obvious), i.e. to the right of the title on the same row.
 *  - The buttons are vertically centered to the middle of the title.
 *
 * Only a real browser computes layout geometry, so these assertions live here
 * (jsdom can't measure getBoundingClientRect / vertical centering).
 */
import { MantineProvider } from '@mantine/core';
import { render } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import '../../../../i18n';
import { CategoryDetailHeader } from '../CategoryDetailHeader';

function mid(el: Element): number {
  const r = el.getBoundingClientRect();
  return r.top + r.height / 2;
}

function renderHeader() {
  return render(
    <MantineProvider defaultColorScheme="light">
      {/* width mirrors the desktop content column so the row doesn't wrap */}
      <div style={{ width: 800 }}>
        <CategoryDetailHeader
          name="Peak Time Techno"
          trackCountLabel="42 tracks"
          onRename={vi.fn()}
          onDelete={vi.fn()}
        />
      </div>
    </MantineProvider>,
  );
}

describe('CategoryDetailHeader — layout (browser)', () => {
  test('Rename/Delete are after the title and vertically centered to it', () => {
    const { container } = renderHeader();
    const title = container.querySelector('h1')!;
    const buttons = Array.from(container.querySelectorAll('button'));
    expect(title).not.toBeNull();
    expect(buttons.length).toBe(2);

    const titleRect = title.getBoundingClientRect();
    for (const btn of buttons) {
      // after the name: the button starts to the right of the title's left edge
      expect(btn.getBoundingClientRect().left).toBeGreaterThan(titleRect.left);
      // vertically centered to the title (within 2px)
      expect(Math.abs(mid(btn) - mid(title))).toBeLessThan(2);
    }
  });
});
