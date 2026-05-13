// frontend/src/test/renderApp.tsx
//
// Shared harness for F6 playback integration tests. Two modes:
//
//   - `renderApp(...)`: MemoryRouter + curate routes only, REAL
//     PlaybackProvider, stub AuthContext. Used by batch 1 + batch 2 — minimal
//     surface, no global chrome.
//
//   - `renderAppWithRouter(...)`: createMemoryRouter (data router) + extra
//     placeholder routes (/tracks, /auth/premium-required, /) + the real
//     PlaybackChrome (DevicePickerSurface). Returns the router instance so
//     tests can drive navigations programmatically via `router.navigate(...)`.
//     Used by batch 3 — exercises route-driven SDK error redirects + the
//     empty-bucket / disconnected PlayerCard states.
//
// Pair with `installSpotifySdkMock()` from ./spotifySdk for tests that exercise
// PlaybackProvider's SDK lifecycle.
import type { ReactNode } from 'react';
import { render, type RenderResult } from '@testing-library/react';
import {
  MemoryRouter,
  Route,
  Routes,
  createMemoryRouter,
  RouterProvider,
  Outlet,
} from 'react-router';
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
import { PlaybackChrome } from '../routes/_layout';

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

/**
 * Stub route components for non-curate paths used by `renderAppWithRouter`. We
 * only need a marker DOM node + the location path itself; tests use
 * `getByTestId(...)` and `router.state.location.pathname` to verify which
 * route is mounted.
 */
function TracksStub() {
  return <div data-testid="tracks-page">tracks placeholder</div>;
}
function HomeStub() {
  return <div data-testid="home-page">home placeholder</div>;
}
function PremiumRequiredStub() {
  return <div data-testid="premium-required-page">premium required</div>;
}

/**
 * Wrapper that mounts both an <Outlet /> (for matched routes) and the
 * PlaybackChrome (DevicePickerSurface). Used as the root data-router route
 * element so PlaybackChrome lives inside the router's location context.
 */
function ChromeShell() {
  return (
    <PlaybackProvider>
      <Outlet />
      <PlaybackChrome />
    </PlaybackProvider>
  );
}

/**
 * Data-router variant of renderApp. Mounts createMemoryRouter +
 * RouterProvider with the real PlaybackChrome (DevicePickerSurface) and
 * returns the router instance so tests can drive navigation via
 * `router.navigate(...)` and assert against `router.state.location.pathname`.
 */
export function renderAppWithRouter(opts: RenderAppOpts): {
  result: RenderResult;
  router: ReturnType<typeof createMemoryRouter>;
} {
  tokenStore.set('TOK');
  spotifyTokenStore.set('SPTOK');
  const refresh = opts.refresh ?? vi.fn().mockResolvedValue(true);
  const auth = makeStubAuth(refresh);
  const qc = makeClient();
  const router = createMemoryRouter(
    [
      {
        element: <ChromeShell />,
        children: [
          { path: '/', element: <HomeStub /> },
          { path: '/tracks', element: <TracksStub /> },
          { path: '/auth/premium-required', element: <PremiumRequiredStub /> },
          { path: '/curate', element: <CurateIndexRedirect /> },
          { path: '/curate/:styleId', element: <CurateStyleResume /> },
          {
            path: '/curate/:styleId/:blockId/:bucketId',
            element: <CurateSessionPage />,
          },
        ],
      },
    ],
    { initialEntries: opts.initialEntries },
  );
  const result = render(
    <I18nextProvider i18n={i18n}>
      <AuthContext.Provider value={auth}>
        <QueryClientProvider client={qc}>
          <MantineProvider theme={testTheme}>
            <Notifications />
            <RouterProvider router={router} />
          </MantineProvider>
        </QueryClientProvider>
      </AuthContext.Provider>
    </I18nextProvider>,
  );
  return { result, router };
}
