import { ApiError } from './error';
import { tokenStore } from '../auth/tokenStore';

const baseUrl =
  typeof window !== 'undefined' && window.location ? window.location.origin : 'http://localhost';

let inflightRefresh: Promise<boolean> | null = null;

interface RefreshResponse {
  access_token: string;
  expires_in: number;
  user: unknown;
}

async function tryRefreshOnce(): Promise<boolean> {
  if (inflightRefresh) return inflightRefresh;
  inflightRefresh = (async () => {
    try {
      const res = await fetch(`${baseUrl}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) return false;
      const body = (await res.json()) as RefreshResponse;
      tokenStore.set(body.access_token);
      window.dispatchEvent(
        new CustomEvent<RefreshResponse>('auth:refreshed', { detail: body }),
      );
      return true;
    } catch {
      return false;
    } finally {
      inflightRefresh = null;
    }
  })();
  return inflightRefresh;
}

function notifyAuthFailure(): void {
  tokenStore.set(null);
  window.dispatchEvent(new CustomEvent('auth:expired'));
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const url = path.startsWith('http') ? path : `${baseUrl}${path}`;
  const token = tokenStore.get();
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

  const res = await fetch(url, { ...init, headers, credentials: 'include' });

  if (res.status === 401 && token) {
    const refreshed = await tryRefreshOnce();
    if (refreshed) {
      const retryHeaders = new Headers(init.headers);
      retryHeaders.set('Accept', 'application/json');
      retryHeaders.set('Authorization', `Bearer ${tokenStore.get()}`);
      if (init.body && !retryHeaders.has('Content-Type')) {
        retryHeaders.set('Content-Type', 'application/json');
      }
      const retry = await fetch(url, { ...init, headers: retryHeaders, credentials: 'include' });
      if (!retry.ok) throw await ApiError.from(retry);
      if (retry.status === 204) return undefined as T;
      return (await retry.json()) as T;
    }
    notifyAuthFailure();
    throw await ApiError.from(res);
  }

  if (!res.ok) throw await ApiError.from(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
