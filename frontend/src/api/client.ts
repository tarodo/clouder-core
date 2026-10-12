import { ApiError } from './error';
import { tokenStore } from '../auth/tokenStore';
import { spotifyTokenStore } from '../auth/spotifyTokenStore';

const baseUrl =
  typeof window !== 'undefined' && window.location ? window.location.origin : 'http://localhost';

export interface RefreshResponse {
  access_token: string;
  spotify_access_token: string;
  expires_in: number;
  user?: unknown;
}

let inflightRefresh: Promise<RefreshResponse | null> | null = null;

/**
 * POST /auth/refresh, single-flight for the whole page: two concurrent calls
 * with one refresh cookie trip replay detection and revoke every session
 * (ADR-0015). Stores the new tokens and raises `auth:refreshed`; null on failure.
 */
export function refreshSession(): Promise<RefreshResponse | null> {
  if (inflightRefresh) return inflightRefresh;
  inflightRefresh = (async () => {
    try {
      const res = await fetch(`${baseUrl}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) return null;
      const body = (await res.json()) as RefreshResponse;
      tokenStore.set(body.access_token);
      spotifyTokenStore.set(body.spotify_access_token);
      window.dispatchEvent(
        new CustomEvent<RefreshResponse>('auth:refreshed', { detail: body }),
      );
      return body;
    } catch {
      return null;
    } finally {
      inflightRefresh = null;
    }
  })();
  return inflightRefresh;
}

function notifyAuthFailure(): void {
  tokenStore.set(null);
  spotifyTokenStore.set(null);
  window.dispatchEvent(new CustomEvent('auth:expired'));
}

export interface ApiInit extends RequestInit {
  suppressAuthFailure?: boolean;
}

export async function api<T = unknown>(path: string, init: ApiInit = {}): Promise<T> {
  const { suppressAuthFailure, ...rest } = init;
  const url = path.startsWith('http') ? path : `${baseUrl}${path}`;
  const token = tokenStore.get();
  const headers = new Headers(rest.headers);
  headers.set('Accept', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (rest.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

  const res = await fetch(url, { ...rest, headers, credentials: 'include' });

  if (res.status === 401 && token) {
    const refreshed = await refreshSession();
    if (refreshed) {
      const retryHeaders = new Headers(rest.headers);
      retryHeaders.set('Accept', 'application/json');
      retryHeaders.set('Authorization', `Bearer ${tokenStore.get()}`);
      if (rest.body && !retryHeaders.has('Content-Type')) {
        retryHeaders.set('Content-Type', 'application/json');
      }
      const retry = await fetch(url, { ...rest, headers: retryHeaders, credentials: 'include' });
      if (!retry.ok) throw await ApiError.from(retry);
      if (retry.status === 204) return undefined as T;
      return (await retry.json()) as T;
    }
    if (!suppressAuthFailure) notifyAuthFailure();
    throw await ApiError.from(res);
  }

  if (!res.ok) throw await ApiError.from(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
