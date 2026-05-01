import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from 'react';
import { ApiError } from '../api/error';
import { api } from '../api/client';
import { tokenStore } from './tokenStore';
import { completeBootstrap } from './bootstrap';

export interface Me {
  id: string;
  spotify_id: string;
  display_name: string;
  is_admin: boolean;
}

interface CallbackResponse {
  access_token: string;
  expires_in: number;
  user: Me;
}

// /auth/refresh returns just the tokens — user identity is implicit (the
// refresh cookie identifies the session). To rebuild AuthProvider state on
// page reload we call /me separately after refresh succeeds.
interface RefreshResponse {
  access_token: string;
  expires_in: number;
}

export type AuthState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'authenticated'; user: Me; expiresAt: number }
  | { status: 'unauthenticated' }
  | { status: 'error'; error: ApiError };

type Action =
  | { type: 'loading' }
  | { type: 'authenticated'; user: Me; expiresAt: number }
  | { type: 'unauthenticated' }
  | { type: 'error'; error: ApiError };

function reducer(_: AuthState, action: Action): AuthState {
  switch (action.type) {
    case 'loading':
      return { status: 'loading' };
    case 'authenticated':
      return { status: 'authenticated', user: action.user, expiresAt: action.expiresAt };
    case 'unauthenticated':
      return { status: 'unauthenticated' };
    case 'error':
      return { status: 'error', error: action.error };
  }
}

let snapshot: AuthState = { status: 'idle' };
export function getAuthSnapshot(): AuthState {
  return snapshot;
}

export interface AuthContextValue {
  state: AuthState;
  signIn: (user: Me, accessToken: string, expiresIn: number) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<boolean>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_LEEWAY_MS = 5 * 60 * 1000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, { status: 'idle' });
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Forward-ref so scheduleRefresh's setTimeout closure always calls the
  // latest refresh function (refresh depends on signIn which depends on
  // scheduleRefresh — break the cycle with a ref).
  const refreshRef = useRef<() => Promise<boolean>>(() => Promise.resolve(false));
  // StrictMode dev-mode runs effects twice (mount → cleanup → mount). Without
  // this guard the bootstrap effect fires two /auth/refresh requests with the
  // same cookie. Backend rotates the token on the first request, then sees
  // the same (now-stale) hash on the second request and triggers replay
  // detection: revokes ALL of the user's sessions. Result: every page
  // refresh requires a fresh OAuth round-trip.
  const bootstrapStarted = useRef(false);

  // Mirror the latest state into the singleton snapshot for non-React readers.
  useEffect(() => {
    snapshot = state;
  }, [state]);

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimer.current !== null) {
      clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
    }
  }, []);

  const scheduleRefresh = useCallback(
    (expiresInMs: number) => {
      clearRefreshTimer();
      const delay = Math.max(0, expiresInMs - REFRESH_LEEWAY_MS);
      refreshTimer.current = setTimeout(() => {
        void refreshRef.current();
      }, delay);
    },
    [clearRefreshTimer],
  );

  const signIn = useCallback(
    (user: Me, accessToken: string, expiresIn: number) => {
      tokenStore.set(accessToken);
      const expiresAt = Date.now() + expiresIn * 1000;
      // Mirror snapshot synchronously — the state-effect mirror runs only on
      // the next render, which races completeBootstrap() and would leave
      // requireAuth seeing the stale 'loading' snapshot, redirecting the
      // just-authenticated user back to /login.
      snapshot = { status: 'authenticated', user, expiresAt };
      dispatch({ type: 'authenticated', user, expiresAt });
      scheduleRefresh(expiresIn * 1000);
    },
    [scheduleRefresh],
  );

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const body = await api<RefreshResponse>('/auth/refresh', { method: 'POST' });
      // Set the new token before fetching /me so the apiClient picks it up
      // for the Authorization header.
      tokenStore.set(body.access_token);
      const user = await api<Me>('/me');
      signIn(user, body.access_token, body.expires_in);
      return true;
    } catch {
      tokenStore.set(null);
      clearRefreshTimer();
      snapshot = { status: 'unauthenticated' };
      dispatch({ type: 'unauthenticated' });
      return false;
    }
  }, [signIn, clearRefreshTimer]);

  // Keep refreshRef pointed at the latest refresh closure.
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  const signOut = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST' });
    } catch {
      // logout always succeeds locally even if remote fails
    }
    tokenStore.set(null);
    clearRefreshTimer();
    snapshot = { status: 'unauthenticated' };
    dispatch({ type: 'unauthenticated' });
  }, [clearRefreshTimer]);

  // Bootstrap on mount: try refresh once, then resolve bootstrapPromise.
  useEffect(() => {
    if (bootstrapStarted.current) return;
    bootstrapStarted.current = true;
    snapshot = { status: 'loading' };
    dispatch({ type: 'loading' });
    void (async () => {
      const ok = await refreshRef.current();
      if (!ok) {
        snapshot = { status: 'unauthenticated' };
        dispatch({ type: 'unauthenticated' });
      }
      completeBootstrap();
    })();
    // Don't clear the refresh timer on cleanup — StrictMode's pretend-unmount
    // would kill the just-scheduled timer for the still-mounted instance. The
    // timer stays valid for the lifetime of the page; signOut is the only
    // thing that should clear it.
  }, []);

  // Listen for auth:expired (raised by apiClient on refresh failure).
  useEffect(() => {
    const onExpired = () => {
      tokenStore.set(null);
      clearRefreshTimer();
      snapshot = { status: 'unauthenticated' };
      dispatch({ type: 'unauthenticated' });
    };
    window.addEventListener('auth:expired', onExpired);
    return () => window.removeEventListener('auth:expired', onExpired);
  }, [clearRefreshTimer]);

  // Listen for auth:refreshed (raised by apiClient after a silent 401-retry
  // refresh). The backend's /auth/refresh response only carries tokens, not
  // the user — silent refresh runs while the user is already authenticated,
  // so we preserve the existing identity and only roll the timer. Tests that
  // dispatch a synthetic event with `user` populated still work — when user
  // is present we update state explicitly.
  useEffect(() => {
    const onRefreshed = (e: Event) => {
      const detail = (e as CustomEvent<Partial<CallbackResponse>>).detail;
      if (!detail || typeof detail.expires_in !== 'number') return;
      if (detail.user) {
        const expiresAt = Date.now() + detail.expires_in * 1000;
        dispatch({ type: 'authenticated', user: detail.user, expiresAt });
      }
      scheduleRefresh(detail.expires_in * 1000);
    };
    window.addEventListener('auth:refreshed', onRefreshed);
    return () => window.removeEventListener('auth:refreshed', onRefreshed);
  }, [scheduleRefresh]);

  const value = useMemo<AuthContextValue>(
    () => ({ state, signIn, signOut, refresh }),
    [state, signIn, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
