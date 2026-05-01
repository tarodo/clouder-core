import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { AuthProvider, getAuthSnapshot } from '../AuthProvider';
import { useAuth } from '../useAuth';
import { tokenStore } from '../tokenStore';
import { resetBootstrapForTests } from '../bootstrap';

function Probe() {
  const { state } = useAuth();
  return <div data-testid="status">{state.status}</div>;
}

describe('AuthProvider', () => {
  beforeEach(() => {
    tokenStore.set(null);
    resetBootstrapForTests();
  });

  it('starts in loading and transitions to authenticated when refresh succeeds', async () => {
    server.use(
      http.post('http://localhost/auth/refresh', () =>
        HttpResponse.json({
          access_token: 'TOK',
          expires_in: 1800,
          user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: false },
        }),
      ),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
    expect(tokenStore.get()).toBe('TOK');
    expect(getAuthSnapshot().status).toBe('authenticated');
  });

  it('transitions to unauthenticated when refresh fails', async () => {
    server.use(
      http.post('http://localhost/auth/refresh', () =>
        HttpResponse.json({ error_code: 'refresh_invalid' }, { status: 401 }),
      ),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
    expect(getAuthSnapshot().status).toBe('unauthenticated');
  });

  it('signOut clears state and calls /auth/logout', async () => {
    let logoutCalls = 0;
    server.use(
      http.post('http://localhost/auth/refresh', () =>
        HttpResponse.json({
          access_token: 'TOK',
          expires_in: 1800,
          user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: false },
        }),
      ),
      http.post('http://localhost/auth/logout', () => {
        logoutCalls += 1;
        return HttpResponse.json({ ok: true });
      }),
    );

    let signOutFn: () => Promise<void> = async () => {};
    function Capture() {
      const auth = useAuth();
      signOutFn = auth.signOut;
      return <Probe />;
    }
    render(
      <AuthProvider>
        <Capture />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));

    await act(async () => {
      await signOutFn();
    });
    expect(logoutCalls).toBe(1);
    expect(tokenStore.get()).toBeNull();
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
  });

  it('reacts to auth:expired window event by switching to unauthenticated', async () => {
    server.use(
      http.post('http://localhost/auth/refresh', () =>
        HttpResponse.json({
          access_token: 'TOK',
          expires_in: 1800,
          user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: false },
        }),
      ),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));

    act(() => {
      window.dispatchEvent(new CustomEvent('auth:expired'));
    });
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
  });

  it('reacts to auth:refreshed event by updating state with the new user', async () => {
    server.use(
      http.post('http://localhost/auth/refresh', () =>
        HttpResponse.json({
          error_code: 'refresh_invalid',
          message: 'no',
          correlation_id: 'c',
        }, { status: 401 }),
      ),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));

    act(() => {
      window.dispatchEvent(
        new CustomEvent('auth:refreshed', {
          detail: {
            access_token: 'FRESH',
            expires_in: 1800,
            user: { id: 'u2', spotify_id: 's2', display_name: 'New', is_admin: false },
          },
        }),
      );
    });
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
  });
});
