import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { server } from '../../test/setup';
import i18n from '../../i18n';
import { AuthContext } from '../../auth/AuthProvider';
import { AuthReturnPage } from '../auth.return';

const signIn = vi.fn();
const auth = {
  state: { status: 'unauthenticated' as const },
  signIn,
  signOut: vi.fn(),
  refresh: vi.fn(),
};

function renderAt(url: string) {
  const router = createMemoryRouter(
    [
      { path: '/auth/return', element: <AuthReturnPage /> },
      { path: '/', element: <div>HOME</div> },
      { path: '/login', element: <div data-testid="login">LOGIN</div> },
    ],
    { initialEntries: [url] },
  );
  return render(
    <I18nextProvider i18n={i18n}>
      <MantineProvider>
        <AuthContext.Provider value={auth}>
          <RouterProvider router={router} />
        </AuthContext.Provider>
      </MantineProvider>
    </I18nextProvider>,
  );
}

describe('AuthReturnPage', () => {
  beforeEach(() => signIn.mockReset());

  it('exchanges code+state and signs in', async () => {
    server.use(
      http.get('http://localhost/auth/callback', () =>
        HttpResponse.json({
          access_token: 'TOK',
          expires_in: 1800,
          user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: false },
        }),
      ),
    );
    renderAt('/auth/return?code=C&state=S');
    await waitFor(() => expect(screen.getByText('HOME')).toBeInTheDocument());
    expect(signIn).toHaveBeenCalledTimes(1);
    expect(signIn.mock.calls[0]?.[1]).toBe('TOK');
  });

  it('shows error and link to /login on validation failure', async () => {
    renderAt('/auth/return');                 // missing code/state
    await waitFor(() => expect(screen.getByText(/missing/i)).toBeInTheDocument());
  });

  it('shows premium error when backend returns account_error', async () => {
    server.use(
      http.get('http://localhost/auth/callback', () =>
        HttpResponse.json(
          { error_code: 'account_error', message: 'premium', correlation_id: 'c' },
          { status: 403 },
        ),
      ),
    );
    renderAt('/auth/return?code=C&state=S');
    await waitFor(() => expect(screen.getByText(/Spotify Premium/i)).toBeInTheDocument());
  });
});
