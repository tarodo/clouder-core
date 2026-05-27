/**
 * Browser-mode layout check for ArtistsPanel: the main ArtistTile renders above
 * the chip row, and multiple chips lay out on the same row (a wrapping Group of
 * inline badges). jsdom can't verify this — no stylesheets — so this lives in
 * the browser harness (Playwright via @vitest/browser).
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import '../../../../i18n';
import { ArtistsPanel } from '../ArtistsPanel';

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistsPanel
            artists={[
              { id: 'a1', name: 'Main Artist' },
              { id: 'a2', name: 'Second' },
              { id: 'a3', name: 'Third' },
            ]}
            styleId="techno"
          />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistsPanel layout (browser)', () => {
  test('chips sit below the main tile and share a row', () => {
    renderPanel();
    const main = screen.getByText('Main Artist').getBoundingClientRect();
    const chip2 = screen.getByRole('button', { name: 'Show Second details' }).getBoundingClientRect();
    const chip3 = screen.getByRole('button', { name: 'Show Third details' }).getBoundingClientRect();

    // Main tile is above the chips.
    expect(chip2.top).toBeGreaterThan(main.top);
    // The two chips share roughly the same row (top within a few px).
    expect(Math.abs(chip2.top - chip3.top)).toBeLessThan(8);
    // Chips are laid out left-to-right.
    expect(chip3.left).toBeGreaterThan(chip2.left);
  });
});
