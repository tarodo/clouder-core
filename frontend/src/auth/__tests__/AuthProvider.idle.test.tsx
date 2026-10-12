import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { api } from '../../api/client';
import { AuthProvider } from '../AuthProvider';
import { useAuth } from '../useAuth';
import { tokenStore } from '../tokenStore';
import { spotifyTokenStore } from '../spotifyTokenStore';
import { resetBootstrapForTests } from '../bootstrap';
import { setSessionKeepAlive } from '../sessionKeepAlive';

// /auth/refresh wakes the scaled-to-zero Aurora for ~10 min. An idle hidden
// tab must not call it on a timer; it catches up when shown again.

// expires_in 300.3 s → the proactive refresh fires ~300 ms after each refresh.
const EXPIRES_IN = 300.3;

let visibility: DocumentVisibilityState = 'visible';
Object.defineProperty(document, 'visibilityState', {
  configurable: true,
  get: () => visibility,
});
function setVisibility(v: DocumentVisibilityState) {
  visibility = v;
  document.dispatchEvent(new Event('visibilitychange'));
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let refreshCalls: number;
let auth: ReturnType<typeof useAuth> | null;

function Capture() {
  auth = useAuth();
  return <div data-testid="status">{auth.state.status}</div>;
}

async function mount() {
  render(
    <AuthProvider>
      <Capture />
    </AuthProvider>,
  );
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
}

describe('AuthProvider idle-tab refresh', () => {
  beforeEach(() => {
    tokenStore.set(null);
    spotifyTokenStore.set(null);
    resetBootstrapForTests();
    refreshCalls = 0;
    auth = null;
    server.use(
      http.post('http://localhost/auth/refresh', async () => {
        refreshCalls += 1;
        await sleep(30);
        return HttpResponse.json({
          access_token: `TOK${refreshCalls}`,
          spotify_access_token: 'SPTOK',
          expires_in: EXPIRES_IN,
        });
      }),
      http.post('http://localhost/auth/logout', () => HttpResponse.json({ ok: true })),
    );
  });

  afterEach(async () => {
    // signOut is the only thing that stops the refresh timer.
    await act(async () => {
      await auth?.signOut();
    });
    // Let an in-flight refresh settle: the single-flight is page-global.
    await sleep(100);
    visibility = 'visible';
    setSessionKeepAlive(false);
  });

  it('a visible tab refreshes before expiry', async () => {
    await mount();
    await waitFor(() => expect(refreshCalls).toBeGreaterThanOrEqual(2), { timeout: 2000 });
  });

  it('a hidden idle tab skips the timed refresh and catches up once when shown', async () => {
    await mount();
    expect(refreshCalls).toBe(1);
    setVisibility('hidden');

    await sleep(900);
    expect(refreshCalls).toBe(1);

    setVisibility('visible');
    await waitFor(() => expect(refreshCalls).toBe(2));
  });

  it('a hidden tab keeps refreshing while music plays', async () => {
    await mount();
    setSessionKeepAlive(true);
    setVisibility('hidden');
    await waitFor(() => expect(refreshCalls).toBeGreaterThanOrEqual(2), { timeout: 2000 });
  });

  it('shares one /auth/refresh with a concurrent 401 retry (replay-safe)', async () => {
    await mount();
    setVisibility('hidden'); // keep the timer out of the count
    let first = true;
    server.use(
      http.get('http://localhost/thing', () => {
        if (first) {
          first = false;
          return HttpResponse.json({ message: 'expired' }, { status: 401 });
        }
        return HttpResponse.json({ ok: true });
      }),
    );
    const before = refreshCalls;

    await act(async () => {
      await Promise.all([auth!.refresh(), api('/thing')]);
    });

    expect(refreshCalls - before).toBe(1);
  });
});
