import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { ArtistsPanel } from '../ArtistsPanel';
import * as client from '../../../../api/client';

function renderPanel(artists: { id: string; name: string; role?: string }[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistsPanel artists={artists} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistsPanel', () => {
  beforeEach(() => vi.restoreAllMocks());

  test('renders nothing when there are no artists', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderPanel([]);
    // MantineProvider injects <style> tags so we cannot assert toBeEmptyDOMElement;
    // instead verify no visible content is rendered.
    expect(document.querySelector('[role], h1, h2, h3, p, a, button, span:not([data-mantine-styles])')).toBeNull();
  });

  test('renders every artist as a tile up front — no chips, no heading', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderPanel(
      [
        { id: 'a1', name: 'Main Artist', role: 'main' },
        { id: 'a2', name: 'Second', role: 'main' },
        { id: 'a3', name: 'Third', role: 'main' },
      ],
    );
    // Each artist is a link to its detail page, expanded from the start.
    expect(screen.getByRole('link', { name: 'Main Artist' })).toHaveAttribute(
      'href',
      '/artists/a1',
    );
    expect(screen.getByRole('link', { name: 'Second' })).toHaveAttribute(
      'href',
      '/artists/a2',
    );
    expect(screen.getByRole('link', { name: 'Third' })).toHaveAttribute(
      'href',
      '/artists/a3',
    );
    // No expand chips remain.
    expect(screen.queryByRole('button', { name: /Show .* details/ })).toBeNull();
  });
});
