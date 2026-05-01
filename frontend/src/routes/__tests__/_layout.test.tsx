import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router';
import i18n from '../../i18n';
import { AuthContext } from '../../auth/AuthProvider';
import { AppShellLayout } from '../_layout';

const auth = {
  state: {
    status: 'authenticated' as const,
    user: { id: 'u', spotify_id: 's', display_name: 'Roman', is_admin: false },
    expiresAt: Date.now() + 1_800_000,
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
        children: [{ path: '/', element: <div data-testid="outlet">HOME</div> }],
      },
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
