import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../../../i18n';
import { tokenStore } from '../../../../auth/tokenStore';
import { ArtistDetailPage } from '../ArtistDetailPage';

const MOCK_ARTIST = {
  artist_name: 'Noisia',
  country: 'NL',
  active_since: 2004,
  tagline: 'Dutch neurofunk trio',
  summary: 'Noisia is a Dutch drum and bass trio.',
  bio: 'Formed in 2000 in Groningen.',
  notable_collaborators: ['Foreign Beggars', 'The Upbeats'],
  primary_styles: ['neurofunk', 'drum and bass'],
  ai_content: 'confirmed',
  ai_reasoning: 'Detected AI-generated content in several tracks.',
  spotify_url: 'https://open.spotify.com/artist/123',
  instagram_url: 'https://instagram.com/noisia',
  my_preference: null,
};

vi.mock('../../hooks/useArtistDetail', () => ({
  useArtistDetail: () => ({
    data: MOCK_ARTIST,
    isLoading: false,
    isError: false,
  }),
}));

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/library/dnb/artists/artist-1']}>
            <Routes>
              <Route
                path="/library/:styleId/artists/:artistId"
                element={<ArtistDetailPage />}
              />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>,
  );
}

describe('ArtistDetailPage', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders the artist name', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'Noisia' })).toBeInTheDocument();
  });

  it('renders the AI badge with confirmed status', () => {
    renderPage();
    const badge = screen.getByText(/AI.*CONFIRMED/i);
    expect(badge).toBeInTheDocument();
  });

  it('renders active_since value', () => {
    renderPage();
    expect(screen.getByText(/2004/)).toBeInTheDocument();
  });

  it('does NOT render a founded_year label', () => {
    renderPage();
    expect(screen.queryByText(/Founded/i)).not.toBeInTheDocument();
  });

  it('renders notable collaborators', () => {
    renderPage();
    expect(screen.getByText('Foreign Beggars')).toBeInTheDocument();
    expect(screen.getByText('The Upbeats')).toBeInTheDocument();
  });

  it('renders the spotify channel link', () => {
    renderPage();
    const spotify = screen.getByRole('link', { name: /spotify/i });
    expect(spotify).toHaveAttribute('href', 'https://open.spotify.com/artist/123');
  });

  it('renders the instagram channel link', () => {
    renderPage();
    const ig = screen.getByRole('link', { name: /instagram/i });
    expect(ig).toHaveAttribute('href', 'https://instagram.com/noisia');
  });
});
