import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

  test('first artist is the main tile; the rest are chips', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderPanel(
      [
        { id: 'a1', name: 'Main Artist', role: 'main' },
        { id: 'a2', name: 'Second', role: 'main' },
        { id: 'a3', name: 'Third', role: 'main' },
      ],
    );
    expect(screen.getByText('Main Artist')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show Second details' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show Third details' })).toBeInTheDocument();
  });

  test('clicking a chip expands it to a tile for that artist', async () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    const user = userEvent.setup();
    renderPanel(
      [
        { id: 'a1', name: 'Main Artist' },
        { id: 'a2', name: 'Second' },
      ],
    );
    await user.click(screen.getByRole('button', { name: 'Show Second details' }));
    expect(await screen.findByRole('link', { name: 'Second' })).toHaveAttribute(
      'href',
      '/artists/a2',
    );
  });
});
