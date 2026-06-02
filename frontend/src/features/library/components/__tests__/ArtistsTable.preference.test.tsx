import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { ArtistsTable } from '../ArtistsTable';
import type { ArtistSummary } from '../../../../api/artists';

function renderTable(items: ArtistSummary[]) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider defaultColorScheme="light">
        <MemoryRouter>
          <ArtistsTable
            items={items}
            isLoading={false}
            page={1}
            pageCount={1}
            onPageChange={() => {}}
          />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ArtistsTable — preference column', () => {
  test('renders like/dislike buttons per row reflecting my_preference', () => {
    renderTable([
      {
        id: 'a1', name: 'Artist One', style: 'techno', status: 'completed',
        track_count: 3, info: { country: 'DE' }, my_preference: 'liked',
      } as ArtistSummary,
    ]);
    expect(screen.getByRole('button', { name: 'Remove preference' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dislike artist' })).toBeInTheDocument();
  });
});
