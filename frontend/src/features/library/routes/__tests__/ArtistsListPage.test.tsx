import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../../../i18n';
import { tokenStore } from '../../../../auth/tokenStore';
import { ArtistsListPage } from '../ArtistsListPage';

vi.mock('../../hooks/useArtistsList', () => ({
  useArtistsList: () => ({
    data: {
      items: [
        {
          id: 'a1',
          name: 'Noisia',
          style: 'dnb',
          status: 'completed',
          track_count: 320,
          info: {
            tagline: 'Dutch neurofunk trio',
            country: 'NL',
            active_since: 2000,
            primary_styles: ['neurofunk'],
            ai_content: 'none_detected',
            updated_at: '2026-05-19T00:00:00Z',
          },
        },
        {
          id: 'a2',
          name: 'Shapeshifter',
          style: 'dnb',
          status: 'completed',
          track_count: 180,
          info: {
            tagline: 'NZ liquid band',
            country: 'NZ',
            active_since: 1999,
            primary_styles: ['liquid'],
            ai_content: null,
            updated_at: '2026-05-20T00:00:00Z',
          },
        },
      ],
      total: 2,
      page: 1,
      limit: 25,
    },
    isLoading: false,
  }),
}));

vi.mock('../../../../hooks/useStyles', () => ({
  useStyles: () => ({ data: { items: [] }, isLoading: false }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/library/dnb/artists']}>
            <Routes>
              <Route path="/library/:styleId/artists" element={<ArtistsListPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

describe('ArtistsListPage', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders both artist names in ArtistsTable', () => {
    renderPage();
    expect(screen.getByText('Noisia')).toBeInTheDocument();
    expect(screen.getByText('Shapeshifter')).toBeInTheDocument();
  });

  it('has an Active since column header', () => {
    renderPage();
    expect(screen.getByText('Active since')).toBeInTheDocument();
  });

  it('does NOT have a Founded column header', () => {
    renderPage();
    expect(screen.queryByText('Founded')).not.toBeInTheDocument();
  });

  it('shows active_since values from artist info', () => {
    renderPage();
    expect(screen.getByText('2000')).toBeInTheDocument();
    expect(screen.getByText('1999')).toBeInTheDocument();
  });
});
