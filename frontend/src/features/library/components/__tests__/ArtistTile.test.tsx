import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { ArtistTile } from '../ArtistTile';
import { artistInfoKey } from '../../hooks/useArtistInfo';
import * as client from '../../../../api/client';

function renderTile(props: { artistId: string | null; artistName?: string }, seed?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (seed && props.artistId) qc.setQueryData(artistInfoKey(props.artistId), seed);
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistTile {...props} />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistTile', () => {
  beforeEach(() => vi.restoreAllMocks());

  test('returns nothing when artistId is null', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderTile({ artistId: null });
    expect(document.querySelector('[data-testid], a, button, p, [role]')).toBeNull();
  });

  test('renders enriched info: name links to the top-level artist page', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderTile(
      { artistId: 'a1', artistName: 'A1' },
      {
        artist_name: 'Aphex',
        country: 'GB',
        active_since: 1991,
        summary: 'Pioneer.',
        notable_collaborators: ['AFX'],
        ai_content: 'confirmed',
        ai_reasoning: 'Synthetic vocals.',
        my_preference: null,
      },
    );
    const link = screen.getByRole('link', { name: 'Aphex' });
    expect(link).toHaveAttribute('href', '/artists/a1');
    expect(screen.getByText('Pioneer.')).toBeInTheDocument();
    expect(screen.getByText('AI CONFIRMED')).toBeInTheDocument();
  });

  test('renders the name as a link even in minimal mode', () => {
    vi.spyOn(client, 'api').mockResolvedValue(undefined as never);
    renderTile({ artistId: 'a1', artistName: 'A1' }, { artist_name: 'NoStyle', my_preference: null });
    expect(screen.getByRole('link', { name: 'NoStyle' })).toHaveAttribute('href', '/artists/a1');
  });
});
