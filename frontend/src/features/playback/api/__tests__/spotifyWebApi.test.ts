import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { spotifyTokenStore } from '../../../../auth/spotifyTokenStore';
import { spotifyApi } from '../spotifyWebApi';

const server = setupServer();

describe('spotifyWebApi', () => {
  beforeEach(() => {
    server.listen({ onUnhandledRequest: 'error' });
    spotifyTokenStore.set('TOKEN');
  });
  afterEach(() => {
    server.close();
    server.resetHandlers();
    spotifyTokenStore.set(null);
  });

  it('attaches Authorization Bearer header', async () => {
    let received: string | null = null;
    server.use(
      http.put('https://api.spotify.com/v1/me/player/play', ({ request }) => {
        received = request.headers.get('authorization');
        return HttpResponse.json({}, { status: 204 });
      }),
    );
    await spotifyApi.play({ uris: ['spotify:track:abc'], deviceId: 'dev1' });
    expect(received).toBe('Bearer TOKEN');
  });

  it('retries once on 401 after auth:refreshed event', async () => {
    let attempts = 0;
    server.use(
      http.put('https://api.spotify.com/v1/me/player/play', () => {
        attempts++;
        if (attempts === 1) return HttpResponse.json({}, { status: 401 });
        return HttpResponse.json({}, { status: 204 });
      }),
    );

    const apiRefresh = vi.fn(async () => {
      spotifyTokenStore.set('FRESH');
      return true;
    });

    await spotifyApi.play(
      { uris: ['spotify:track:abc'], deviceId: 'dev1' },
      { onAuthExpired: apiRefresh },
    );

    expect(apiRefresh).toHaveBeenCalledTimes(1);
    expect(attempts).toBe(2);
  });

  it('throws on second 401', async () => {
    server.use(
      http.put('https://api.spotify.com/v1/me/player/play', () =>
        HttpResponse.json({}, { status: 401 }),
      ),
    );
    const apiRefresh = vi.fn(async () => true);
    await expect(
      spotifyApi.play(
        { uris: ['spotify:track:abc'], deviceId: 'dev1' },
        { onAuthExpired: apiRefresh },
      ),
    ).rejects.toThrow(/401/);
  });

  it('PUT /me/player calls transferMyPlayback', async () => {
    const captured: { body: { device_ids?: string[] } | null } = { body: null };
    server.use(
      http.put('https://api.spotify.com/v1/me/player', async ({ request }) => {
        captured.body = (await request.json()) as { device_ids?: string[] };
        return HttpResponse.json({}, { status: 204 });
      }),
    );
    await spotifyApi.transferMyPlayback({ deviceId: 'dev1', play: false });
    expect(captured.body?.device_ids).toEqual(['dev1']);
  });

  it('seek hits /me/player/seek with position_ms query', async () => {
    const captured: { url: URL | null } = { url: null };
    server.use(
      http.put('https://api.spotify.com/v1/me/player/seek', ({ request }) => {
        captured.url = new URL(request.url);
        return HttpResponse.json({}, { status: 204 });
      }),
    );
    await spotifyApi.seek({ positionMs: 12345, deviceId: 'dev1' });
    expect(captured.url?.searchParams.get('position_ms')).toBe('12345');
    expect(captured.url?.searchParams.get('device_id')).toBe('dev1');
  });
});
