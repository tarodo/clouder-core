/**
 * Browser smoke test for ProfilePage — the route changed from a centered
 * `<Center mih="60vh">` block to a top-aligned `Container` + `Group` +
 * `Divider` layout, and had no test of any kind. jsdom applies no
 * stylesheets, so whether the header row and MyStylesSection actually sit
 * apart (rather than overlapping) can only be verified with real geometry.
 *
 * No *.browser.test.tsx in this repo wires up msw (see
 * MyStylesSection.browser.test.tsx) — `api/client` is replaced directly with
 * vi.mock instead, and auth state is supplied via AuthContext.Provider
 * (see routes/__tests__/_layout.test.tsx for the jsdom equivalent of this
 * fixture).
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import '../../i18n';
import { AuthContext, type AuthContextValue } from '../../auth/AuthProvider';
import { ProfilePage } from '../profile';

// vi.mock factories are hoisted above imports; vi.hoisted() gives the factory
// a reference that exists before that hoist, avoiding a TDZ read on a
// module-scope `let`.
const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));

vi.mock('../../api/client', () => ({ api: apiMock }));

const catalog = {
  items: [
    { id: 's1', name: 'Drum & Bass', selected: true, position: 0 },
    { id: 's2', name: 'House', selected: false, position: null },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

const auth: AuthContextValue = {
  state: {
    status: 'authenticated',
    user: {
      id: 'u1',
      spotify_id: 'sp1',
      display_name: 'Roman',
      is_admin: false,
      ytmusic_connected: false,
    },
    expiresAt: Date.now() + 1_800_000,
    spotifyAccessToken: 'SPTOK',
  },
  signIn: () => {},
  signOut: async () => {},
  refresh: async () => false,
};

function renderPage() {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) => {
    if (path.startsWith('/styles')) return catalog;
    throw new Error(`unexpected api call: ${path}`);
  });

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        {/* Fixed width so the header Group's justify="space-between" lays
            out on one row regardless of the default browser-mode viewport. */}
        <div style={{ width: 900 }}>
          <AuthContext.Provider value={auth}>
            <ProfilePage />
          </AuthContext.Provider>
        </div>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('ProfilePage (browser)', () => {
  it('renders heading, sign-out and styles section without overlap', async () => {
    renderPage();

    const heading = screen.getByRole('heading', { name: 'Profile' });
    const signOut = screen.getByRole('button', { name: /Sign out/i });
    await screen.findByText('Drum & Bass');
    const stylesHeading = screen.getByRole('heading', { name: 'My styles' });

    expect(heading).toBeVisible();
    expect(signOut).toBeVisible();
    expect(stylesHeading).toBeVisible();

    const headingRect = heading.getBoundingClientRect();
    const signOutRect = signOut.getBoundingClientRect();
    const stylesRect = stylesHeading.getBoundingClientRect();

    // Sign-out sits to the right of the page heading (Group justify="space-between"),
    // not stacked on top of it.
    expect(signOutRect.left).toBeGreaterThan(headingRect.right);
    // The styles section sits below the whole header row — no vertical overlap.
    expect(stylesRect.top).toBeGreaterThanOrEqual(headingRect.bottom);
    expect(stylesRect.top).toBeGreaterThanOrEqual(signOutRect.bottom);
  });
});
