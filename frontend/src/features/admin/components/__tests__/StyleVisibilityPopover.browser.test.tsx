import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import '../../../../i18n';
import { StyleVisibilityPopover } from '../StyleVisibilityPopover';

const styles = [
  {
    style_id: 100,
    clouder_style_id: 'uuid-bf',
    style_name: 'Brazilian Funk',
    is_hidden: true,
    cells: [],
    spotify_weeks: [],
  },
  {
    style_id: 90,
    clouder_style_id: 'uuid-th',
    style_name: 'Tech House',
    is_hidden: false,
    cells: [],
    spotify_weeks: [],
  },
];

describe('StyleVisibilityPopover layout', () => {
  test('dropdown opens under the right-aligned button and stays on screen', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MantineProvider>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <StyleVisibilityPopover styles={styles} />
          </div>
        </MantineProvider>
      </QueryClientProvider>,
    );

    const button = screen.getByRole('button', { name: 'Styles · 1 hidden' });
    await userEvent.click(button);
    const checkbox = await screen.findByRole('checkbox', { name: 'Tech House' });

    const dropdown = checkbox.closest('.mantine-Popover-dropdown');
    expect(dropdown).not.toBeNull();
    const box = dropdown!.getBoundingClientRect();
    const btn = button.getBoundingClientRect();
    expect(box.top).toBeGreaterThanOrEqual(btn.bottom);
    expect(box.left).toBeGreaterThanOrEqual(0);
    expect(box.right).toBeLessThanOrEqual(window.innerWidth);
    // The hint wraps instead of stretching the dropdown across the page.
    expect(box.width).toBeLessThan(320);
  });
});
