import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, renderHook, screen, act, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { testTheme } from '../../../test/theme';
import { PlaybackProvider } from '../PlaybackProvider';
import { usePlayback } from '../usePlayback';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { AuthContext, type AuthContextValue } from '../../../auth/AuthProvider';
import { __resetSdkLoaderForTests } from '../lib/sdkLoader';
import {
  installSpotifySdkMock,
  uninstallSpotifySdkMock,
} from '../../../test/spotifySdk';

function makeStubAuth(refresh: AuthContextValue['refresh'] = vi.fn().mockResolvedValue(true)): AuthContextValue {
  return {
    state: {
      status: 'authenticated',
      user: { id: 'u', spotify_id: 's', display_name: 'Test', is_admin: false },
      expiresAt: Date.now() + 1_800_000,
      spotifyAccessToken: 'SPTOK',
    },
    signIn: vi.fn(),
    signOut: vi.fn(),
    refresh,
  };
}

function makeAuthWrapper(auth: AuthContextValue = makeStubAuth()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <AuthContext.Provider value={auth}>
        <PlaybackProvider>{children}</PlaybackProvider>
      </AuthContext.Provider>
    );
  };
}

function Probe() {
  const playback = usePlayback();
  return (
    <div>
      <span data-testid="status">{playback.queue.status}</span>
      <span data-testid="cursor">{playback.queue.cursor}</span>
      <span data-testid="sdk-ready">{String(playback.sdk.ready)}</span>
    </div>
  );
}

describe('PlaybackProvider scaffold', () => {
  it('exposes idle queue + sdk.ready=false at mount', () => {
    render(
      <AuthContext.Provider value={makeStubAuth()}>
        <MantineProvider theme={testTheme}>
          <PlaybackProvider>
            <Probe />
          </PlaybackProvider>
        </MantineProvider>
      </AuthContext.Provider>,
    );
    expect(screen.getByTestId('status').textContent).toBe('idle');
    expect(screen.getByTestId('cursor').textContent).toBe('0');
    expect(screen.getByTestId('sdk-ready').textContent).toBe('false');
  });

  it('throws if usePlayback called outside provider', () => {
    expect(() => render(<Probe />)).toThrow(/PlaybackProvider/);
  });
});

const sdkServer = setupServer();

describe('PlaybackProvider SDK lifecycle', () => {
  beforeEach(() => {
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
    spotifyTokenStore.set('SPTOK');
    sdkServer.listen({ onUnhandledRequest: 'bypass' });
  });
  afterEach(() => {
    uninstallSpotifySdkMock();
    spotifyTokenStore.set(null);
    sdkServer.close();
    sdkServer.resetHandlers();
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
  });

  it('does not load SDK on mount', () => {
    renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    expect(document.head.querySelector('script[data-spotify-sdk]')).toBeNull();
  });

  it('ensureSdk loads SDK + creates Player + transfers playback to ready device', async () => {
    const captured: {
      transferBody: { device_ids?: string[]; play?: boolean } | null;
    } = { transferBody: null };
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player', async ({ request }) => {
        captured.transferBody = (await request.json()) as typeof captured.transferBody;
        return HttpResponse.json({}, { status: 204 });
      }),
    );
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    await act(async () => {
      await result.current.controls.play(0);
    });
    act(() => {
      handle.getLatest()?.__emit('ready', { device_id: 'cl-tab-1' });
    });
    await waitFor(() => {
      expect(captured.transferBody?.device_ids).toEqual(['cl-tab-1']);
      expect(captured.transferBody?.play).toBe(false);
    });
    await waitFor(() => {
      expect(result.current.sdk.ready).toBe(true);
    });
  });

  it('bindQueue stores source/tracks/cursor and reads it back', () => {
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    const tracks = [
      { id: 'A', title: 'A', artists: 'A', cover_url: null, duration_ms: 1000, spotify_id: 'spA' },
    ];
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b1', bucketId: 'u1' },
        tracks,
        cursor: 0,
        onCursorChange: vi.fn(),
      });
    });
    expect(result.current.queue.source).toEqual({ type: 'bucket', blockId: 'b1', bucketId: 'u1' });
    expect(result.current.queue.tracks).toEqual(tracks);
    expect(result.current.queue.cursor).toBe(0);
  });

  it('player_state_changed updates positionMs and durationMs', async () => {
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    await act(async () => { await result.current.controls.play(); });
    act(() => {
      handle.getLatest()?.__emit('ready', { device_id: 'd1' });
    });
    act(() => {
      handle.getLatest()?.__emit('player_state_changed', {
        paused: false,
        position: 12345,
        duration: 60000,
        track_window: { current_track: { id: 'sp1' } },
      });
    });
    await waitFor(() => {
      expect(result.current.track.positionMs).toBe(12345);
      expect(result.current.track.durationMs).toBe(60000);
    });
  });

  it('player_state_changed with paused:true sets queue.status=paused', async () => {
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    await act(async () => { await result.current.controls.play(); });
    act(() => {
      handle.getLatest()?.__emit('ready', { device_id: 'd1' });
    });
    act(() => {
      handle.getLatest()?.__emit('player_state_changed', {
        paused: true,
        position: 0,
        duration: 60000,
        track_window: { current_track: { id: 'sp1' } },
      });
    });
    await waitFor(() => {
      expect(result.current.queue.status).toBe('paused');
    });
  });

  it('controls.play(idx) calls Spotify Web API play with spotify URI of tracks[idx]', async () => {
    const captured: { body: { uris?: string[] } | null } = { body: null };
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', async ({ request }) => {
        captured.body = (await request.json()) as { uris?: string[] };
        return HttpResponse.json({}, { status: 204 });
      }),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'A', title: 'A', artists: '', cover_url: null, duration_ms: 1000, spotify_id: 'spA' },
          { id: 'B', title: 'B', artists: '', cover_url: null, duration_ms: 1000, spotify_id: 'spB' },
        ],
        cursor: 0,
        onCursorChange: vi.fn(),
      });
    });
    await act(async () => {
      await result.current.controls.play(1);
    });
    act(() => {
      handle.getLatest()?.__emit('ready', { device_id: 'd1' });
    });
    // After ready fires, cursor=1; trigger play() again now that device exists.
    await act(async () => {
      await result.current.controls.play(1);
    });
    await waitFor(() => {
      expect(captured.body?.uris).toEqual(['spotify:track:spB']);
    });
  });

  it('controls.play() with no idx uses cursor track', async () => {
    const captured: { body: { uris?: string[] } | null } = { body: null };
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', async ({ request }) => {
        captured.body = (await request.json()) as { uris?: string[] };
        return HttpResponse.json({}, { status: 204 });
      }),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'A', title: 'A', artists: '', cover_url: null, duration_ms: 1000, spotify_id: 'spA' },
        ],
        cursor: 0,
        onCursorChange: vi.fn(),
      });
    });
    await act(async () => { await result.current.controls.play(); });
    act(() => {
      handle.getLatest()?.__emit('ready', { device_id: 'd1' });
    });
    await act(async () => { await result.current.controls.play(); });
    await waitFor(() => {
      expect(captured.body?.uris).toEqual(['spotify:track:spA']);
    });
  });

  it('controls.play(idx) is a no-op when track has null spotify_id', async () => {
    const captured: { calls: number } = { calls: 0 };
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', () => {
        captured.calls++;
        return HttpResponse.json({}, { status: 204 });
      }),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'X', title: 'X', artists: '', cover_url: null, duration_ms: 1000, spotify_id: null },
        ],
        cursor: 0,
        onCursorChange: vi.fn(),
      });
    });
    await act(async () => { await result.current.controls.play(0); });
    act(() => {
      handle.getLatest()?.__emit('ready', { device_id: 'd1' });
    });
    await act(async () => { await result.current.controls.play(0); });
    // Wait a tick; ensure /play never fires (it would have by now if it were going to)
    await new Promise((r) => setTimeout(r, 50));
    expect(captured.calls).toBe(0);
  });

  it('togglePlayPause calls SDK togglePlay', async () => {
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    await act(async () => { await result.current.controls.togglePlayPause(); });
    expect(handle.getLatest()?.togglePlay).toHaveBeenCalled();
  });

  it('next advances cursor + plays next playable track', async () => {
    const onCursorChange = vi.fn();
    const handle = installSpotifySdkMock();
    const captured: { body: { uris?: string[] } | null } = { body: null };
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', async ({ request }) => {
        captured.body = (await request.json()) as { uris?: string[] };
        return HttpResponse.json({}, { status: 204 });
      }),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'A', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spA' },
          { id: 'B', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: null },
          { id: 'C', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spC' },
        ],
        cursor: 0,
        onCursorChange,
      });
    });
    await act(async () => { await result.current.controls.play(0); });
    act(() => { handle.getLatest()?.__emit('ready', { device_id: 'd1' }); });
    await act(async () => { await result.current.controls.play(0); });
    await waitFor(() => expect(captured.body?.uris).toEqual(['spotify:track:spA']));
    await act(async () => { await result.current.controls.next(); });
    expect(onCursorChange).toHaveBeenLastCalledWith(2);
    await waitFor(() => expect(captured.body?.uris).toEqual(['spotify:track:spC']));
  });

  it('next on last playable enters ended state and pauses', async () => {
    const handle = installSpotifySdkMock();
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', () => HttpResponse.json({}, { status: 204 })),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'A', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spA' },
        ],
        cursor: 0,
        onCursorChange: vi.fn(),
      });
    });
    await act(async () => { await result.current.controls.play(0); });
    act(() => { handle.getLatest()?.__emit('ready', { device_id: 'd1' }); });
    await act(async () => { await result.current.controls.next(); });
    await waitFor(() => expect(result.current.queue.status).toBe('ended'));
    expect(handle.getLatest()?.pause).toHaveBeenCalled();
  });

  it('prev steps backward through playable tracks', async () => {
    const onCursorChange = vi.fn();
    const handle = installSpotifySdkMock();
    const captured: { body: { uris?: string[] } | null } = { body: null };
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', async ({ request }) => {
        captured.body = (await request.json()) as { uris?: string[] };
        return HttpResponse.json({}, { status: 204 });
      }),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'A', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spA' },
          { id: 'B', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: null },
          { id: 'C', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spC' },
        ],
        cursor: 2,
        onCursorChange,
      });
    });
    await act(async () => { await result.current.controls.play(2); });
    act(() => { handle.getLatest()?.__emit('ready', { device_id: 'd1' }); });
    await act(async () => { await result.current.controls.play(2); });
    await act(async () => { await result.current.controls.prev(); });
    expect(onCursorChange).toHaveBeenLastCalledWith(0);
    await waitFor(() => expect(captured.body?.uris).toEqual(['spotify:track:spA']));
  });

  it('seekMs clamps to [0, duration] and calls SDK seek', async () => {
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    await act(async () => { await result.current.controls.play(); });
    act(() => { handle.getLatest()?.__emit('ready', { device_id: 'd1' }); });
    act(() => {
      handle.getLatest()?.__emit('player_state_changed', {
        paused: false, position: 0, duration: 60000, track_window: { current_track: { id: 'x' } },
      });
    });
    await waitFor(() => expect(result.current.track.durationMs).toBe(60000));
    await act(async () => { await result.current.controls.seekMs(-100); });
    expect(handle.getLatest()?.seek).toHaveBeenLastCalledWith(0);
    await act(async () => { await result.current.controls.seekMs(99999); });
    expect(handle.getLatest()?.seek).toHaveBeenLastCalledWith(60000);
  });

  it('seekPct(0.6) of 360s == 216000ms', async () => {
    const handle = installSpotifySdkMock();
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    await act(async () => { await result.current.controls.play(); });
    act(() => { handle.getLatest()?.__emit('ready', { device_id: 'd1' }); });
    act(() => {
      handle.getLatest()?.__emit('player_state_changed', {
        paused: false, position: 0, duration: 360000, track_window: { current_track: { id: 'x' } },
      });
    });
    await waitFor(() => expect(result.current.track.durationMs).toBe(360000));
    await act(async () => { await result.current.controls.seekPct(0.6); });
    expect(handle.getLatest()?.seek).toHaveBeenLastCalledWith(216000);
  });

  it('cancelPendingAdvance prevents the next-after-200ms call', async () => {
    vi.useFakeTimers();
    const handle = installSpotifySdkMock();
    const captured: { calls: number } = { calls: 0 };
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', () => {
        captured.calls++;
        return HttpResponse.json({}, { status: 204 });
      }),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'A', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spA' },
          { id: 'B', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spB' },
        ],
        cursor: 0,
        onCursorChange: vi.fn(),
      });
    });
    // Use real timers for the SDK boot, fake for the schedule
    vi.useRealTimers();
    await act(async () => { await result.current.controls.play(0); });
    act(() => { handle.getLatest()?.__emit('ready', { device_id: 'd1' }); });
    await act(async () => { await result.current.controls.play(0); });
    // initial play call counted; reset
    captured.calls = 0;
    vi.useFakeTimers();
    act(() => {
      (result.current.controls as unknown as {
        __schedulePendingAdvance: (direction: 1 | -1, delay: number) => void;
      }).__schedulePendingAdvance(+1, 200);
    });
    act(() => {
      result.current.controls.cancelPendingAdvance();
    });
    act(() => { vi.advanceTimersByTime(250); });
    vi.useRealTimers();
    // Allow microtasks to flush
    await new Promise((r) => setTimeout(r, 30));
    expect(captured.calls).toBe(0);
  });

  it('clearQueue resets to idle and pauses SDK', async () => {
    const handle = installSpotifySdkMock();
    sdkServer.use(
      http.put('https://api.spotify.com/v1/me/player/play', () => HttpResponse.json({}, { status: 204 })),
      http.put('https://api.spotify.com/v1/me/player', () => HttpResponse.json({}, { status: 204 })),
    );
    const { result } = renderHook(() => usePlayback(), { wrapper: makeAuthWrapper() });
    act(() => {
      result.current.controls.bindQueue({
        source: { type: 'bucket', blockId: 'b', bucketId: 'u' },
        tracks: [
          { id: 'A', title: '', artists: '', cover_url: null, duration_ms: 1, spotify_id: 'spA' },
        ],
        cursor: 0,
        onCursorChange: vi.fn(),
      });
    });
    await act(async () => { await result.current.controls.play(0); });
    act(() => { handle.getLatest()?.__emit('ready', { device_id: 'd1' }); });
    act(() => { result.current.controls.clearQueue(); });
    await waitFor(() => expect(result.current.queue.status).toBe('idle'));
    expect(result.current.queue.source).toBeNull();
    expect(handle.getLatest()?.pause).toHaveBeenCalled();
  });
});
