import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { tokenStore } from '../../../../auth/tokenStore';
import { AuthContext, type AuthContextValue } from '../../../../auth/AuthProvider';
import { server } from '../../../../test/setup';
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

function makeAuth(is_admin = false): AuthContextValue {
  return {
    state: {
      status: 'authenticated',
      user: { id: 'u', spotify_id: 's', display_name: 'Test User', is_admin, ytmusic_connected: false },
      expiresAt: Date.now() + 1_800_000,
      spotifyAccessToken: null,
    },
    signIn: vi.fn(),
    signOut: vi.fn(),
    refresh: vi.fn(),
  };
}

function renderPage(auth: AuthContextValue = makeAuth()) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <AuthContext.Provider value={auth}>
            <MemoryRouter initialEntries={['/artists/artist-1']}>
              <Routes>
                <Route path="/artists/:artistId" element={<ArtistDetailPage />} />
                <Route path="/library" element={<div>LIBRARY</div>} />
              </Routes>
            </MemoryRouter>
          </AuthContext.Provider>
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

  it('renders a back control', () => {
    renderPage();
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
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

  it('shows no "Search now" button for non-admins', async () => {
    renderPage(makeAuth(false));
    await screen.findByRole('heading', { level: 2 });
    expect(screen.queryByRole('button', { name: /search now/i })).not.toBeInTheDocument();
  });

  it('shows a working "Search now" button for admins', async () => {
    let posted = false;
    server.use(
      http.post('http://localhost/admin/artists/:id/enrich-auto', () => {
        posted = true;
        return HttpResponse.json({ run_id: 'run-1', queued_artists: 1 }, { status: 202 });
      }),
    );
    renderPage(makeAuth(true));
    const btn = await screen.findByRole('button', { name: /search now/i });
    await userEvent.click(btn);
    await waitFor(() => expect(posted).toBe(true));
  });
});
