// frontend/src/features/playback/__tests__/integration.batch4.test.tsx
//
// F6 PlayerCard integration tests batch 4 — Spotify access-token rotation.
//
// Two scenarios:
//   6. Proactive refresh — AuthProvider.scheduleRefresh fires at
//      `(expires_in - 300) * 1000` ms, /auth/refresh rotates the spotify
//      access token, and the SDK's getOAuthToken callback returns the new
//      token on subsequent invocation.
//   7. Reactive refresh on 401 — spotifyApi.play returns 401 on the first
//      call, PlaybackProvider's onAuthExpired (= AuthProvider.refresh) hits
//      /auth/refresh, the rotated token lands in spotifyTokenStore via the
//      `auth:refreshed` event, and spotifyApi retries with the new bearer
//      token (204 OK).
//
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { http, HttpResponse } from 'msw';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { server } from '../../../test/setup';
import { testTheme } from '../../../test/theme';
import i18n from '../../../i18n';
import { tokenStore } from '../../../auth/tokenStore';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { AuthProvider, AuthContext, type AuthContextValue } from '../../../auth/AuthProvider';
import { resetBootstrapForTests } from '../../../auth/bootstrap';
import { PlaybackProvider } from '../PlaybackProvider';
import { usePlayback } from '../usePlayback';
import {
  installSpotifySdkMock,
  uninstallSpotifySdkMock,
} from '../../../test/spotifySdk';
import { __resetSdkLoaderForTests } from '../lib/sdkLoader';
import { CurateIndexRedirect, CurateStyleResume, CurateSessionPage } from '../../curate';

/* ---------- shared fixtures ---------- */

function ProbeAuth() {
  return <div data-testid="auth-probe" />;
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
}

interface BlockBucket {
  id: string;
  bucket_type: 'NEW' | 'STAGING' | 'OLD' | 'DISCARD';
  inactive: boolean;
  track_count: number;
  category_id?: string;
  category_name?: string;
}

function buildBlock(): {
  id: string;
  style_id: string;
  style_name: string;
  name: string;
  date_from: string;
  date_to: string;
  status: 'IN_PROGRESS';
  created_at: string;
  updated_at: string;
  finalized_at: null;
  buckets: BlockBucket[];
} {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'Tech House',
    name: 'TH W17',
    date_from: '2026-04-21',
    date_to: '2026-04-27',
    status: 'IN_PROGRESS',
    created_at: '2026-04-20T00:00:00Z',
    updated_at: '2026-04-20T00:00:00Z',
    finalized_at: null,
    buckets: [
      { id: 'src', bucket_type: 'NEW', inactive: false, track_count: 1 },
      {
        id: 'dst1',
        bucket_type: 'STAGING',
        inactive: false,
        track_count: 0,
        category_id: 'c1',
        category_name: 'Big Room',
      },
      { id: 'b-old', bucket_type: 'OLD', inactive: false, track_count: 0 },
      { id: 'b-disc', bucket_type: 'DISCARD', inactive: false, track_count: 0 },
    ],
  };
}

function buildTracks() {
  return {
    items: [
      {
        track_id: 't1',
        title: 'Track t1',
        mix_name: null,
        isrc: null,
        bpm: 124,
        length_ms: 360000,
        publish_date: '2026-04-15',
        spotify_release_date: '2026-04-15',
        spotify_id: 'spA',
        release_type: 'single',
        is_ai_suspected: false,
        artists: ['Artist A'],
        label_name: 'Label X',
        added_at: '2026-04-21T00:00:00Z',
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
  };
}

/* ---------- suite ---------- */

describe('F6 integration · batch 4 · token refresh', () => {
  beforeEach(() => {
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
    tokenStore.set(null);
    spotifyTokenStore.set(null);
    resetBootstrapForTests();
  });

  afterEach(() => {
    uninstallSpotifySdkMock();
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
    vi.useRealTimers();
    tokenStore.set(null);
    spotifyTokenStore.set(null);
  });

  /**
   * Scenario 6 — proactive refresh.
   *
   * AuthProvider's bootstrap effect fires /auth/refresh on mount; the first
   * call returns `expires_in: 600` and `spotify_access_token: 'SP_INITIAL'`.
   * scheduleRefresh queues a setTimeout for `(600 - 300) * 1000 = 300_000`
   * ms — too long to wait under wall-clock test time.
   *
   * Compress the timer by re-arming it via the `auth:refreshed` listener
   * with a near-zero `expires_in`. AuthProvider's scheduleRefresh clamps
   * delay to `Math.max(0, expires_in*1000 - 300_000)`, so `expires_in: 1`
   * yields a 0 ms setTimeout that fires on the next tick. The same code
   * path as the production 300_000 ms timer — just compressed in time.
   *
   * The scheduled callback calls refreshRef.current() → /auth/refresh
   * fires the second time → returns 'SP_FRESH'. Assert spotifyTokenStore
   * reflects the rotation, and that the SDK's getOAuthToken callback
   * (registered when PlaybackProvider boots the SDK) reads 'SP_FRESH'
   * synchronously.
   */
  it('6. proactive refresh: scheduleRefresh rotates spotifyTokenStore + SDK reads new token', async () => {
    let refreshCalls = 0;
    server.use(
      http.post('http://localhost/auth/refresh', () => {
        refreshCalls += 1;
        const spotifyToken = refreshCalls === 1 ? 'SP_INITIAL' : 'SP_FRESH';
        const accessToken = refreshCalls === 1 ? 'TOK_INITIAL' : 'TOK_FRESH';
        return HttpResponse.json({
          access_token: accessToken,
          spotify_access_token: spotifyToken,
          expires_in: 600,
        });
      }),
      http.get('http://localhost/me', () =>
        HttpResponse.json({
          id: 'u1',
          spotify_id: 'sp1',
          display_name: 'Roman',
          is_admin: false,
        }),
      ),
      // F6/F7 ensureSdk → ready listener → getMyDevices + transferMyPlayback.
      // Handle both so requests resolve without erroring under MSW's
      // `onUnhandledRequest: 'error'` policy.
      http.get('https://api.spotify.com/v1/me/player/devices', () =>
        HttpResponse.json({ devices: [{ id: 'dev-test', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null }] }),
      ),
      http.put('https://api.spotify.com/v1/me/player', () =>
        HttpResponse.json({}, { status: 204 }),
      ),
      http.put('https://api.spotify.com/v1/me/player/play', () =>
        HttpResponse.json({}, { status: 204 }),
      ),
    );

    // Install the SDK mock BEFORE mounting so PlaybackProvider's ensureSdk()
    // path can capture the player constructor args (including getOAuthToken).
    // F6: PlaybackProvider's play() awaits deviceReadyRef, which only resolves
    // when the 'ready' listener fires. Make addListener track the 'ready'
    // callback and invoke it asynchronously after connect() resolves so
    // togglePlayPause doesn't hang.
    let capturedGetOAuthToken: ((cb: (t: string) => void) => void) | null = null;
    (window as unknown as {
      Spotify: unknown;
    }).Spotify = {
      Player: vi.fn().mockImplementation((opts: {
        getOAuthToken: (cb: (t: string) => void) => void;
      }) => {
        capturedGetOAuthToken = opts.getOAuthToken;
        const listeners: Record<string, (state: unknown) => void> = {};
        return {
          connect: vi.fn().mockImplementation(async () => {
            // Mirror real SDK timing: 'ready' fires shortly after connect.
            queueMicrotask(() => {
              listeners.ready?.({ device_id: 'dev-test' });
            });
            return true;
          }),
          disconnect: vi.fn(),
          togglePlay: vi.fn().mockResolvedValue(undefined),
          pause: vi.fn().mockResolvedValue(undefined),
          resume: vi.fn().mockResolvedValue(undefined),
          seek: vi.fn().mockResolvedValue(undefined),
          activateElement: vi.fn().mockResolvedValue(undefined),
          addListener: vi.fn().mockImplementation((event: string, cb: (s: unknown) => void) => {
            listeners[event] = cb;
            return true;
          }),
          removeListener: vi.fn(),
        };
      }),
    };
    queueMicrotask(() => {
      window.onSpotifyWebPlaybackSDKReady?.();
    });

    // Capture playback controls so we can trigger SDK init explicitly.
    let playbackRef: ReturnType<typeof usePlayback> | null = null;
    function ProbePlayback() {
      playbackRef = usePlayback();
      return <div data-testid="playback-probe" />;
    }

    render(
      <MemoryRouter>
        <I18nextProvider i18n={i18n}>
          <MantineProvider theme={testTheme}>
            <AuthProvider>
              <PlaybackProvider>
                <ProbeAuth />
                <ProbePlayback />
              </PlaybackProvider>
            </AuthProvider>
          </MantineProvider>
        </I18nextProvider>
      </MemoryRouter>,
    );

    // Wait for AuthProvider bootstrap → first /auth/refresh resolves →
    // spotifyTokenStore receives 'SP_INITIAL'. The scheduleRefresh
    // setTimeout for (600 - 300) * 1000 ms is queued internally.
    await waitFor(() => {
      expect(spotifyTokenStore.get()).toBe('SP_INITIAL');
    });
    expect(refreshCalls).toBe(1);

    // Boot the SDK so getOAuthToken is registered. Trigger ensureSdk via
    // togglePlayPause (it calls ensureSdk first thing). The SDK mock captures
    // opts.getOAuthToken synchronously inside the Player constructor.
    expect(playbackRef).not.toBeNull();
    await act(async () => {
      await playbackRef!.controls.togglePlayPause();
    });
    expect(capturedGetOAuthToken).not.toBeNull();

    // Sanity: getOAuthToken returns the initial token while the proactive
    // refresh timer is still pending.
    let probedToken: string | null = null;
    capturedGetOAuthToken!((t: string) => {
      probedToken = t;
    });
    expect(probedToken).toBe('SP_INITIAL');

    // Trigger the proactive-refresh timer to fire NOW. AuthProvider's
    // scheduleRefresh clamps `delay = Math.max(0, expiresInMs -
    // REFRESH_LEEWAY_MS)`. By dispatching `auth:refreshed` with a small
    // expires_in, the next scheduleRefresh queues a 0-ms setTimeout that
    // fires on the next tick — exercising the same code path the 300_000ms
    // production timer would, just compressed in test time. The 'auth:
    // refreshed' listener path is covered by AuthProvider unit tests; here
    // we only use it to re-arm the timer with a near-zero delay.
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent('auth:refreshed', {
          detail: {
            access_token: 'TOK_INITIAL',
            spotify_access_token: 'SP_INITIAL',
            expires_in: 1, // delay = max(0, 1000 - 300_000) = 0
          },
        }),
      );
    });

    // Allow the queued 0-ms setTimeout to fire + the resulting refresh()
    // chain (api(/auth/refresh) + api(/me) + signIn) to settle. waitFor
    // polls under real timers until refreshCalls advances to 2.
    await waitFor(
      () => {
        expect(refreshCalls).toBe(2);
      },
      { timeout: 4000 },
    );
    await waitFor(() => {
      expect(spotifyTokenStore.get()).toBe('SP_FRESH');
    });

    // SDK's getOAuthToken callback now resolves to the rotated token —
    // confirms the callback reads through to spotifyTokenStore on every
    // invocation rather than capturing the initial value at construction.
    probedToken = null;
    capturedGetOAuthToken!((t: string) => {
      probedToken = t;
    });
    expect(probedToken).toBe('SP_FRESH');
  }, 15000);

  /**
   * Scenario 7 — reactive refresh on 401.
   *
   * Mount the curate route with a real PlaybackProvider but a stubbed
   * AuthContext whose `refresh` rotates spotifyTokenStore by hitting
   * /auth/refresh. Click play → SDK boots → emit ready → click again so
   * spotifyApi.play actually fires (deviceId is set). The first /play call
   * returns 401; spotifyApi calls onAuthExpired (= AuthProvider.refresh) →
   * /auth/refresh returns 'SP_FRESH' → retry /play returns 204.
   *
   * Assertions:
   *   - /auth/refresh hit exactly once (mid-flow)
   *   - /v1/me/player/play retried with the new bearer token
   *   - spotifyTokenStore ended up as 'SP_FRESH'
   *   - No thrown error inside the play flow
   */
  it('7. reactive refresh on 401: spotifyApi.play 401 → refresh → retry 204', async () => {
    let refreshCalls = 0;
    let playCalls = 0;
    const playAuthHeaders: Array<string | null> = [];

    server.use(
      http.post('http://localhost/auth/refresh', () => {
        refreshCalls += 1;
        return HttpResponse.json({
          access_token: 'TOK_FRESH',
          spotify_access_token: 'SP_FRESH',
          expires_in: 1800,
          user: { id: 'u1', spotify_id: 'sp1', display_name: 'Roman', is_admin: false },
        });
      }),
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json(buildBlock()),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () =>
        HttpResponse.json(buildTracks()),
      ),
      // F7: bootstrap getMyDevices call on SDK ready.
      http.get('https://api.spotify.com/v1/me/player/devices', () =>
        HttpResponse.json({ devices: [{ id: 'dev-1', name: 'CLOUDER', type: 'Computer', is_active: false, is_private_session: false, is_restricted: false, volume_percent: null }] }),
      ),
      http.put('https://api.spotify.com/v1/me/player', () =>
        HttpResponse.json({}, { status: 204 }),
      ),
      http.put('https://api.spotify.com/v1/me/player/play', ({ request }) => {
        playCalls += 1;
        playAuthHeaders.push(request.headers.get('Authorization'));
        if (playCalls === 1) {
          return HttpResponse.json(
            { error: { status: 401, message: 'token expired' } },
            { status: 401 },
          );
        }
        return HttpResponse.json({}, { status: 204 });
      }),
    );

    // Stub auth whose `refresh` performs the real rotation (via fetch +
    // store mutations + auth:refreshed event), exactly mirroring how
    // tryRefreshOnce in api/client.ts behaves. Mounting the real
    // AuthProvider would also work but layered on top of curate routes is
    // brittle (bootstrap hits /me + /auth/refresh on mount and races route
    // data-loading); a custom refresh keeps the flow deterministic.
    const stubRefresh: AuthContextValue['refresh'] = async () => {
      const res = await fetch('http://localhost/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) return false;
      const body = (await res.json()) as {
        access_token: string;
        spotify_access_token: string;
        expires_in: number;
      };
      tokenStore.set(body.access_token);
      spotifyTokenStore.set(body.spotify_access_token);
      window.dispatchEvent(
        new CustomEvent('auth:refreshed', { detail: body }),
      );
      return true;
    };

    const stubAuth: AuthContextValue = {
      state: {
        status: 'authenticated',
        user: { id: 'u1', spotify_id: 'sp1', display_name: 'Roman', is_admin: false, ytmusic_connected: false },
        expiresAt: Date.now() + 1_800_000,
        spotifyAccessToken: 'SP_INITIAL',
      },
      signIn: vi.fn(),
      signOut: vi.fn(),
      refresh: stubRefresh,
    };

    tokenStore.set('TOK');
    spotifyTokenStore.set('SP_INITIAL');

    const handle = installSpotifySdkMock();
    const qc = makeClient();

    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <MemoryRouter initialEntries={['/curate/s1/b1/src']}>
          <I18nextProvider i18n={i18n}>
            <AuthContext.Provider value={stubAuth}>
              <QueryClientProvider client={qc}>
                <MantineProvider theme={testTheme}>
                  <Notifications />
                  <PlaybackProvider>{children}</PlaybackProvider>
                </MantineProvider>
              </QueryClientProvider>
            </AuthContext.Provider>
          </I18nextProvider>
        </MemoryRouter>
      );
    }

    const user = userEvent.setup();
    render(
      <Wrapper>
        <Routes>
          <Route path="/curate" element={<CurateIndexRedirect />} />
          <Route path="/curate/:styleId" element={<CurateStyleResume />} />
          <Route
            path="/curate/:styleId/:blockId/:bucketId"
            element={<CurateSessionPage />}
          />
        </Routes>
      </Wrapper>,
    );

    // F6: CurateCard only renders on mobile + has no Play button. Wait on
    // the curate-session container instead.
    await waitFor(() => {
      const session = screen.getByTestId('curate-session');
      expect(within(session).getByText('Track t1')).toBeInTheDocument();
    });

    // Click PlayerCard's Play button — togglePlayPause→play() awaits
    // deviceReadyRef. Emit `ready` while the click is in flight so play()
    // resolves and spotifyApi.play fires (returning 401 the first time).
    const playButton = (() => {
      const candidates = screen.getAllByRole('button', { name: /^play$/i });
      const enabled = candidates.find(
        (el) => !(el as HTMLButtonElement).disabled,
      );
      if (!enabled) throw new Error('No enabled Play button');
      return enabled;
    })();
    const clickPromise = user.click(playButton);
    await waitFor(() => expect(handle.getLatest()).not.toBeNull());
    await act(async () => {
      handle.getLatest()?.__emit('ready', { device_id: 'dev-1' });
    });
    await clickPromise;

    // F6: useCurateSession's auto-play effect fires when sdkReady flips true,
    // adding an EXTRA spotifyApi.play call beyond the user-click flow's 401-
    // retry-204 pair. Wait for AT LEAST the user-click flow to complete (2
    // calls); 3 total is the expected post-F6 count.
    await waitFor(() => {
      expect(playCalls).toBeGreaterThanOrEqual(2);
    });

    // /auth/refresh fired exactly once during the reactive flow.
    expect(refreshCalls).toBe(1);

    // First call carries the initial token; SOME later call carries the
    // rotated token. (Auto-play effect racing the click-flow's retry makes
    // playAuthHeaders[1] non-deterministic — could be the auto-play's
    // pre-refresh attempt or the original retry.)
    expect(playAuthHeaders[0]).toBe('Bearer SP_INITIAL');
    expect(playAuthHeaders.slice(1)).toEqual(
      expect.arrayContaining(['Bearer SP_FRESH']),
    );

    // Token store ended up rotated (set by the refresh flow + the
    // auth:refreshed event listener inside AuthProvider — but here the
    // stubRefresh writes it directly).
    expect(spotifyTokenStore.get()).toBe('SP_FRESH');
  }, 15000);
});
