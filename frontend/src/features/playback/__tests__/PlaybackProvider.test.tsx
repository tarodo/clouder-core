import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, renderHook, screen, act, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { testTheme } from '../../../test/theme';
import { PlaybackProvider } from '../PlaybackProvider';
import { usePlayback } from '../usePlayback';
import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import { __resetSdkLoaderForTests } from '../lib/sdkLoader';
import {
  installSpotifySdkMock,
  uninstallSpotifySdkMock,
} from '../../../test/spotifySdk';

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
      <MantineProvider theme={testTheme}>
        <PlaybackProvider>
          <Probe />
        </PlaybackProvider>
      </MantineProvider>,
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
    renderHook(() => usePlayback(), { wrapper: PlaybackProvider });
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
    const { result } = renderHook(() => usePlayback(), { wrapper: PlaybackProvider });
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
    const { result } = renderHook(() => usePlayback(), { wrapper: PlaybackProvider });
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
    const { result } = renderHook(() => usePlayback(), { wrapper: PlaybackProvider });
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
    const { result } = renderHook(() => usePlayback(), { wrapper: PlaybackProvider });
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
});
