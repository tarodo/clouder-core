/**
 * Browser-mode layout check for ArtistsPanel: every artist renders as a full
 * ArtistTile up front (no chips, no expand step), stacked vertically. jsdom
 * can't verify layout — no stylesheets — so this lives in the browser harness
 * (Playwright via @vitest/browser).
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
          />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistsPanel layout (browser)', () => {
  test('every artist is a tile, stacked vertically', () => {
    renderPanel();
    const main = screen.getByRole('link', { name: 'Main Artist' }).getBoundingClientRect();
    const second = screen.getByRole('link', { name: 'Second' }).getBoundingClientRect();
    const third = screen.getByRole('link', { name: 'Third' }).getBoundingClientRect();

    // Tiles stack top-to-bottom, one per row.
    expect(second.top).toBeGreaterThan(main.top);
    expect(third.top).toBeGreaterThan(second.top);
  });
});
