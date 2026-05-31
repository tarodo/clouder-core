import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router';
import i18n from '../../i18n';
import { testTheme } from '../../test/theme';
import { AuthContext } from '../../auth/AuthProvider';
import { AppShellLayout } from '../_layout';

const auth = {
  state: {
    status: 'authenticated' as const,
    user: { id: 'u', spotify_id: 's', display_name: 'Roman', is_admin: false, ytmusic_connected: false },
    expiresAt: Date.now() + 1_800_000,
    spotifyAccessToken: 'SPTOK' as string | null,
  },
  signIn: () => {},
  signOut: async () => {},
  refresh: async () => false,
};

function renderAt(url: string) {
  const router = createMemoryRouter(
    [
      {
        element: <AppShellLayout />,
        children: [
          { path: '/', element: <div data-testid="outlet">HOME</div> },
          { path: '/tracks', element: <div data-testid="outlet">TRACKS</div> },
          {
            path: '/curate/:styleId/:blockId/:bucketId',
            element: <div data-testid="outlet">CURATE</div>,
          },
        ],
      },
    ],
    { initialEntries: [url] },
  );
  return render(
    <I18nextProvider i18n={i18n}>
      <MantineProvider theme={testTheme}>
        <AuthContext.Provider value={auth}>
          <RouterProvider router={router} />
        </AuthContext.Provider>
      </MantineProvider>
    </I18nextProvider>,
  );
}

describe('AppShellLayout', () => {
  it('renders wordmark + UserMenu + outlet', () => {
    renderAt('/');
    expect(screen.getByText('CLOUDER')).toBeInTheDocument();
    expect(screen.getByText('Roman')).toBeInTheDocument();
    expect(screen.getByTestId('outlet')).toBeInTheDocument();
  });

  it('renders navigation items', () => {
    renderAt('/');
    expect(screen.getAllByRole('link', { name: /home/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /categories/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /triage/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /curate/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /profile/i }).length).toBeGreaterThan(0);
  });
});

describe('AppShellLayout admin nav', () => {
  it('shows Admin nav link for is_admin: true', () => {
    const adminAuth = {
      ...auth,
      state: {
        ...auth.state,
        user: { ...auth.state.user, is_admin: true },
      },
    };
    const router = createMemoryRouter(
      [
        {
          element: <AppShellLayout />,
          children: [{ path: '/', element: <div data-testid="outlet">HOME</div> }],
        },
      ],
      { initialEntries: ['/'] },
    );
    render(
      <I18nextProvider i18n={i18n}>
        <MantineProvider theme={testTheme}>
          <AuthContext.Provider value={adminAuth}>
            <RouterProvider router={router} />
          </AuthContext.Provider>
        </MantineProvider>
      </I18nextProvider>,
    );
    expect(screen.getAllByRole('link', { name: /admin/i }).length).toBeGreaterThan(0);
  });

  it('does not show Admin nav link for is_admin: false', () => {
    renderAt('/');
    expect(screen.queryByRole('link', { name: /admin/i })).toBeNull();
  });
});
