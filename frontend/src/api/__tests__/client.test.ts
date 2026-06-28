import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { api } from '../client';
import { ApiError } from '../error';
import { tokenStore } from '../../auth/tokenStore';
import { spotifyTokenStore } from '../../auth/spotifyTokenStore';

describe('api()', () => {
  beforeEach(() => {
    tokenStore.set(null);
    spotifyTokenStore.set(null);
    // reset auth-failure listeners
    window.removeEventListener('auth:expired', authFailHandler);
    authFailFired = false;
    window.addEventListener('auth:expired', authFailHandler);
  });

  it('attaches Bearer token when set', async () => {
    tokenStore.set('TOK');
    let seen: string | null = null;
    server.use(
      http.get('http://localhost/me', ({ request }) => {
        seen = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    await api('/me');
    expect(seen).toBe('Bearer TOK');
  });

  it('parses JSON success response', async () => {
    server.use(http.get('http://localhost/me', () => HttpResponse.json({ id: 'x' })));
    const out = await api<{ id: string }>('/me');
    expect(out).toEqual({ id: 'x' });
  });

  it('throws ApiError on non-2xx', async () => {
    server.use(
      http.get('http://localhost/me', () =>
        HttpResponse.json(
          { error_code: 'forbidden', message: 'no', correlation_id: 'c' },
          { status: 403 },
        ),
      ),
    );
    await expect(api('/me')).rejects.toBeInstanceOf(ApiError);
  });

  it('refreshes token on 401 and retries once', async () => {
    tokenStore.set('STALE');
    let attempt = 0;
    server.use(
      http.get('http://localhost/me', () => {
        attempt += 1;
        if (attempt === 1) {
          return HttpResponse.json(
            { error_code: 'unauthorized', message: 'expired', correlation_id: 'c' },
            { status: 401 },
          );
        }
        return HttpResponse.json({ id: 'after-refresh' });
      }),
      http.post('http://localhost/auth/refresh', () =>
        HttpResponse.json({
          access_token: 'FRESH',
          spotify_access_token: 'SP_FRESH',
          expires_in: 1800,
          user: { id: 'u', spotify_id: 's', display_name: 'd', is_admin: false },
        }),
      ),
    );

    const out = await api<{ id: string }>('/me');
    expect(out).toEqual({ id: 'after-refresh' });
    expect(tokenStore.get()).toBe('FRESH');
    expect(spotifyTokenStore.get()).toBe('SP_FRESH');
    expect(attempt).toBe(2);
  });

  it('fires auth:expired event when refresh fails', async () => {
    tokenStore.set('STALE');
    spotifyTokenStore.set('SOMETHING');
    server.use(
      http.get('http://localhost/me', () =>
        HttpResponse.json(
          { error_code: 'unauthorized', message: 'x', correlation_id: 'c' },
          { status: 401 },
        ),
      ),
      http.post('http://localhost/auth/refresh', () =>
        HttpResponse.json(
          { error_code: 'refresh_invalid', message: 'no', correlation_id: 'c' },
          { status: 401 },
        ),
      ),
    );

    await expect(api('/me')).rejects.toBeInstanceOf(ApiError);
    expect(authFailFired).toBe(true);
    expect(tokenStore.get()).toBeNull();
    expect(spotifyTokenStore.get()).toBeNull();
  });
});

let authFailFired = false;
function authFailHandler() {
  authFailFired = true;
}

describe('api() suppressAuthFailure', () => {
  beforeEach(() => {
    tokenStore.set('jwt-1');
    spotifyTokenStore.set('sp-jwt-1');
  });
  afterEach(() => {
    vi.restoreAllMocks();
    tokenStore.set(null);
    spotifyTokenStore.set(null);
  });

  function mock401ThenRefreshFail() {
    // Every request (incl. /auth/refresh) 401s → refresh fails → unrecoverable 401.
    return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 401 }));
  }

  it('default path logs the user out on unrecoverable 401', async () => {
    mock401ThenRefreshFail();
    const expired = vi.fn();
    window.addEventListener('auth:expired', expired);
    await expect(api('/me')).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledTimes(1);
    expect(tokenStore.get()).toBeNull();
    window.removeEventListener('auth:expired', expired);
  });

  it('suppressed path swallows logout: no auth:expired, token kept', async () => {
    mock401ThenRefreshFail();
    const expired = vi.fn();
    window.addEventListener('auth:expired', expired);
    await expect(
      api('/v1/telemetry', { method: 'POST', keepalive: true, suppressAuthFailure: true, body: '{}' }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(expired).not.toHaveBeenCalled();
    expect(tokenStore.get()).toBe('jwt-1');
    expect(spotifyTokenStore.get()).toBe('sp-jwt-1');
    window.removeEventListener('auth:expired', expired);
  });

  it('forwards keepalive to fetch and never leaks suppressAuthFailure into RequestInit', async () => {
    // 202 with parseable body; empty body would throw 'Unexpected end of JSON input'.
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 202 }));
    await api('/v1/telemetry', { method: 'POST', keepalive: true, suppressAuthFailure: true, body: '{}' });
    expect(spy).toHaveBeenCalledOnce();
    const init = spy.mock.calls[0]![1] as RequestInit & { suppressAuthFailure?: unknown };
    expect(init.keepalive).toBe(true);
    expect('suppressAuthFailure' in init).toBe(false);
  });
});
