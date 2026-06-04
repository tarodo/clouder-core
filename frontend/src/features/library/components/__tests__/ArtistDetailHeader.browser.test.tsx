/**
 * Browser-mode layout regression for ArtistDetailHeader.
 *
 * Verifies that the Back link sits INLINE (same row, to the LEFT) of the
 * artist name heading, not on a separate row above it.
 *
 * jsdom can't verify getBoundingClientRect geometry — this lives in the
 * browser harness (@vitest/browser + Playwright).
 */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import '../../../../i18n';
import { AuthContext, type AuthContextValue } from '../../../../auth/AuthProvider';
import { ArtistDetailHeader } from '../ArtistDetailHeader';
import type { ArtistDetail } from '../../../../api/artists';

const stubAuth: AuthContextValue = {
  state: {
    status: 'authenticated',
    user: { id: 'u1', spotify_id: 'sp1', display_name: 'Test User', is_admin: false, ytmusic_connected: false },
    expiresAt: Date.now() + 1_800_000,
    spotifyAccessToken: 'SPTOK',
  },
  signIn: vi.fn(),
  signOut: vi.fn(),
  refresh: vi.fn().mockResolvedValue(true),
};

const mockInfo = {
  artist_name: 'Test Artist',
  ai_content: '',
  ai_reasoning: '',
  country: 'DE',
  active_since: 2010,
  my_preference: null,
} as unknown as ArtistDetail;

function renderHeader() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthContext.Provider value={stubAuth}>
        <MantineProvider defaultColorScheme="light">
          <MemoryRouter initialEntries={['/library/artists/a1']}>
            {/* wide container so the row doesn't wrap */}
            <div style={{ width: 900 }}>
              <ArtistDetailHeader info={mockInfo} artistId="a1" />
            </div>
          </MemoryRouter>
        </MantineProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

describe('ArtistDetailHeader — back-link inline layout (browser)', () => {
  test('Back link and artist title are on the same row', () => {
    renderHeader();

    const back = screen.getByRole('button', { name: '← Back' });
    const title = screen.getByRole('heading', { level: 2, name: 'Test Artist' });

    const backRect = back.getBoundingClientRect();
    const titleRect = title.getBoundingClientRect();

    // Same row: vertical centres are within 24px of each other
    expect(Math.abs(backRect.top - titleRect.top)).toBeLessThan(24);
  });

  test('Back link is to the LEFT of the artist title', () => {
    renderHeader();

    const back = screen.getByRole('button', { name: '← Back' });
    const title = screen.getByRole('heading', { level: 2, name: 'Test Artist' });

    expect(back.getBoundingClientRect().left).toBeLessThan(title.getBoundingClientRect().left);
  });
});
