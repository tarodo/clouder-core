import { describe, it, expect, beforeEach, afterEach } from 'vitest';
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
});
