import { afterEach, describe, expect, it, vi } from 'vitest';
import { spotifyTokenStore } from '../../../../auth/spotifyTokenStore';
import { spotifyApi } from '../spotifyWebApi';

vi.mock('../../../../demo/mode', () => ({ isDemo: () => true }));

describe('spotifyWebApi in the demo', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    spotifyTokenStore.set(null);
  });

  it('never calls api.spotify.com, even with a token', async () => {
    spotifyTokenStore.set('demo');
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await expect(spotifyApi.getTrackCover('abc')).rejects.toThrow('spotify_unavailable_in_demo');
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
