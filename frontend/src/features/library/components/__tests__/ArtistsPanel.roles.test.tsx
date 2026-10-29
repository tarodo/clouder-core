import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it } from 'vitest';
import '../../../../i18n';
import { ArtistsPanel } from '../ArtistsPanel';

it('shows an artist credited twice once, with both credits', () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MantineProvider>
        <MemoryRouter>
          <ArtistsPanel
            artists={[
              { id: 'a1', name: 'Ivory (IT)', role: 'main' },
              { id: 'a2', name: 'Julia Linkogel', role: 'main' },
              { id: 'a1', name: 'Ivory (IT)', role: 'remixer' },
            ]}
          />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
  expect(screen.getAllByRole('link', { name: 'Ivory (IT)' })).toHaveLength(1);
  expect(screen.getByText('Artist · Remixer')).toBeInTheDocument();
});
