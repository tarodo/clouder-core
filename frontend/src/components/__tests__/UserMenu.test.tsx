import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../i18n';
import { AuthContext, type AuthContextValue } from '../../auth/AuthProvider';
import { UserMenu } from '../UserMenu';

function makeAuth(signOut: AuthContextValue['signOut'] = vi.fn()): AuthContextValue {
  return {
    state: {
      status: 'authenticated',
      user: { id: 'u', spotify_id: 's', display_name: 'Roman', is_admin: false },
      expiresAt: Date.now() + 1_800_000,
    },
    signIn: vi.fn(),
    signOut,
    refresh: vi.fn(),
  };
}

function wrap(ui: React.ReactNode, auth: AuthContextValue = makeAuth()) {
  return render(
    <I18nextProvider i18n={i18n}>
      <MantineProvider>
        <AuthContext.Provider value={auth}>{ui}</AuthContext.Provider>
      </MantineProvider>
    </I18nextProvider>,
  );
}

describe('UserMenu', () => {
  it('shows display name', () => {
    wrap(<UserMenu />);
    expect(screen.getByText(/Roman/)).toBeInTheDocument();
  });

  it('calls signOut from menu', async () => {
    const signOut = vi.fn();
    wrap(<UserMenu />, makeAuth(signOut));
    await userEvent.click(screen.getByRole('button', { name: /Roman/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /sign out/i }));
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it('renders nothing when unauthenticated', () => {
    const auth = {
      state: { status: 'unauthenticated' as const },
      signIn: vi.fn(),
      signOut: vi.fn(),
      refresh: vi.fn(),
    };
    wrap(<UserMenu />, auth);
    // MantineProvider injects a <style> tag, so we check that no UserMenu
    // button is rendered rather than asserting an empty DOM.
    expect(screen.queryByRole('button')).toBeNull();
  });
});
