import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../i18n';

// Force desktop so the Burger + navbar render (jsdom has no matchMedia match).
vi.mock('@mantine/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mantine/hooks')>();
  return { ...actual, useMediaQuery: () => true };
});
// UserMenu uses useAuth(); stub it so the layout test needs no auth provider.
vi.mock('../../components/UserMenu', () => ({ UserMenu: () => null }));

import { AppShellInner } from '../_layout';

function r() {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <AppShellInner />
      </MantineProvider>
    </MemoryRouter>,
  );
}

describe('AppShellInner navbar toggle', () => {
  it('toggles the navbar collapse via the Burger', async () => {
    r();
    const burger = screen.getByLabelText('Toggle navigation');
    expect(burger).toHaveAttribute('aria-expanded', 'true'); // expanded by default
    await userEvent.click(burger);
    expect(burger).toHaveAttribute('aria-expanded', 'false'); // collapsed
    await userEvent.click(burger);
    expect(burger).toHaveAttribute('aria-expanded', 'true'); // expanded again
  });
});
