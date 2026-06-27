import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';
import { ApiError } from './error';
import { tokenStore } from '../auth/tokenStore';

describe('api() suppressAuthFailure', () => {
  beforeEach(() => tokenStore.set('jwt-1'));
  afterEach(() => {
    vi.restoreAllMocks();
    tokenStore.set(null);
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
    window.removeEventListener('auth:expired', expired);
  });

  it('forwards keepalive to fetch and never leaks suppressAuthFailure into RequestInit', async () => {
    // 202 with a parseable body: api() does `await res.json()` on non-204 success,
    // and Response.json() on an empty body throws 'Unexpected end of JSON input'.
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 202 }));
    await api('/v1/telemetry', { method: 'POST', keepalive: true, suppressAuthFailure: true, body: '{}' });
    const init = spy.mock.calls[0]![1] as RequestInit & { suppressAuthFailure?: unknown };
    expect(init.keepalive).toBe(true);
    expect('suppressAuthFailure' in init).toBe(false);
  });
});
