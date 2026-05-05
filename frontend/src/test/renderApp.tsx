// frontend/src/test/renderApp.tsx
//
// Shared harness for F6 playback integration tests. Mounts the curate route
// tree (CurateIndexRedirect / CurateStyleResume / CurateSessionPage) inside a
// MemoryRouter wrapped with the REAL PlaybackProvider plus a stub
// AuthContext.Provider. Skips the AppShell + requireAuth gate to keep the test
// surface focused — F5's curate-flow tests use the same shortcut.
//
// Pair with `installSpotifySdkMock()` from ./spotifySdk for tests that exercise
// PlaybackProvider's SDK lifecycle.
import type { ReactNode } from 'react';
import { render, type RenderResult } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { I18nextProvider } from 'react-i18next';
import { vi } from 'vitest';
import { testTheme } from './theme';
import i18n from '../i18n';
import { tokenStore } from '../auth/tokenStore';
import { spotifyTokenStore } from '../auth/spotifyTokenStore';
import { AuthContext, type AuthContextValue } from '../auth/AuthProvider';
import { PlaybackProvider } from '../features/playback/PlaybackProvider';
import {
  CurateIndexRedirect,
  CurateStyleResume,
  CurateSessionPage,
} from '../features/curate';

export interface RenderAppOpts {
  /** Initial MemoryRouter entry, e.g. '/curate/s1/b1/src'. */
  initialEntries: string[];
  /** Stub AuthContext refresh fn (defaults to vi.fn returning true). */
  refresh?: AuthContextValue['refresh'];
  /**
   * Children to render inside the providers but outside the route tree.
   * Useful for harness probes; defaults to the curate routes.
   */
  children?: ReactNode;
}

function makeStubAuth(refresh: AuthContextValue['refresh']): AuthContextValue {
  return {
    state: {
      status: 'authenticated',
      user: { id: 'u1', spotify_id: 'sp1', display_name: 'Roman', is_admin: false },
      expiresAt: Date.now() + 1_800_000,
      spotifyAccessToken: 'SPTOK',
    },
    signIn: vi.fn(),
    signOut: vi.fn(),
    refresh,
  };
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

export function renderApp(opts: RenderAppOpts): RenderResult {
  tokenStore.set('TOK');
  spotifyTokenStore.set('SPTOK');
  const refresh = opts.refresh ?? vi.fn().mockResolvedValue(true);
  const auth = makeStubAuth(refresh);
  const qc = makeClient();
  return render(
    <MemoryRouter initialEntries={opts.initialEntries}>
      <I18nextProvider i18n={i18n}>
        <AuthContext.Provider value={auth}>
          <QueryClientProvider client={qc}>
            <MantineProvider theme={testTheme}>
              <Notifications />
              <PlaybackProvider>
                {opts.children ?? (
                  <Routes>
                    <Route path="/curate" element={<CurateIndexRedirect />} />
                    <Route path="/curate/:styleId" element={<CurateStyleResume />} />
                    <Route
                      path="/curate/:styleId/:blockId/:bucketId"
                      element={<CurateSessionPage />}
                    />
                  </Routes>
                )}
              </PlaybackProvider>
            </MantineProvider>
          </QueryClientProvider>
        </AuthContext.Provider>
      </I18nextProvider>
    </MemoryRouter>,
  );
}
