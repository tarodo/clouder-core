import { afterEach, describe, expect, it, vi } from 'vitest';
import { spotifyTokenStore } from '../../../../auth/spotifyTokenStore';
import { setDemoSpotifyApi } from '../../../../demo/spotifyBridge';
import { spotifyApi } from '../spotifyWebApi';

vi.mock('../../../../demo/mode', () => ({ isDemo: () => true }));

describe('spotifyWebApi in the demo', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setDemoSpotifyApi(null);
    spotifyTokenStore.set(null);
  });

  it('answers through the demo player and never calls api.spotify.com', async () => {
    spotifyTokenStore.set('demo');
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const calls: string[] = [];
    setDemoSpotifyApi(async (method, path) => {
      calls.push(`${method} ${path}`);
      return new Response(JSON.stringify({ devices: [{ id: 'clouder-demo' }] }), { status: 200 });
    });
    const devices = await spotifyApi.getMyDevices();
    expect(devices.map((d) => d.id)).toEqual(['clouder-demo']);
    expect(calls).toEqual(['GET /v1/me/player/devices']);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('refuses before the demo player is installed', async () => {
    await expect(spotifyApi.getTrackCover('abc')).rejects.toThrow('spotify_unavailable_in_demo');
  });
});
