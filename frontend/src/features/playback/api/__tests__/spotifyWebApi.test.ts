import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { spotifyTokenStore } from '../../../../auth/spotifyTokenStore';
import { spotifyApi } from '../spotifyWebApi';
import type { SpotifyDevice } from '../../lib/deviceTypes';

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

describe('spotifyApi.getMyDevices', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    spotifyTokenStore.set('token-1');
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
  });
  afterEach(() => {
    spotifyTokenStore.set(null);
    vi.unstubAllGlobals();
  });

  it('returns devices on 200', async () => {
    const devices: SpotifyDevice[] = [{ id: 'd1', name: 'Laptop', type: 'Computer', is_active: true, is_private_session: false, is_restricted: false, volume_percent: 60 }];
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ devices }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    const result = await spotifyApi.getMyDevices();
    expect(result).toEqual(devices);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('https://api.spotify.com/v1/me/player/devices');
    expect((init as RequestInit).method).toBe('GET');
    expect(((init as RequestInit).headers as Record<string, string>).Authorization).toBe('Bearer token-1');
  });

  it('retries once on 401 if onAuthExpired returns true', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockImplementationOnce(async () => {
        // simulate token rotated by AuthProvider
        spotifyTokenStore.set('token-2');
        return new Response(JSON.stringify({ devices: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      });
    const onAuthExpired = vi.fn(async () => true);
    const result = await spotifyApi.getMyDevices({ onAuthExpired });
    expect(result).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onAuthExpired).toHaveBeenCalledTimes(1);
  });

  it('throws on 500', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 500 }));
    await expect(spotifyApi.getMyDevices()).rejects.toThrow(/spotify_api_500/);
  });

  it('returns [] when devices field is missing', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    const result = await spotifyApi.getMyDevices();
    expect(result).toEqual([]);
  });
});
