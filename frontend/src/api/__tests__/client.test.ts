import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/setup';
import { api } from '../client';
import { ApiError } from '../error';
import { tokenStore } from '../../auth/tokenStore';

describe('api()', () => {
  beforeEach(() => {
    tokenStore.set(null);
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
          expires_in: 1800,
          user: { id: 'u', spotify_id: 's', display_name: 'd', is_admin: false },
        }),
      ),
    );

    const out = await api<{ id: string }>('/me');
    expect(out).toEqual({ id: 'after-refresh' });
    expect(tokenStore.get()).toBe('FRESH');
    expect(attempt).toBe(2);
  });

  it('fires auth:expired event when refresh fails', async () => {
    tokenStore.set('STALE');
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
  });
});

let authFailFired = false;
function authFailHandler() {
  authFailFired = true;
}
