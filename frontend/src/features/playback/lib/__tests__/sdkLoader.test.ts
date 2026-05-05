import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { loadSpotifySdk, __resetSdkLoaderForTests } from '../sdkLoader';

describe('sdkLoader.loadSpotifySdk', () => {
  beforeEach(() => {
    __resetSdkLoaderForTests();
    document.head.querySelectorAll('script[data-spotify-sdk]').forEach((s) => s.remove());
    delete (window as unknown as { Spotify?: unknown }).Spotify;
    delete (window as unknown as { onSpotifyWebPlaybackSDKReady?: unknown })
      .onSpotifyWebPlaybackSDKReady;
  });

  afterEach(() => {
    __resetSdkLoaderForTests();
  });

  it('injects the script once on first call', () => {
    void loadSpotifySdk();
    const tags = document.head.querySelectorAll('script[data-spotify-sdk]');
    expect(tags.length).toBe(1);
    expect(tags[0]?.getAttribute('src')).toBe('https://sdk.scdn.co/spotify-player.js');
  });

  it('does not inject a second tag on second call', () => {
    void loadSpotifySdk();
    void loadSpotifySdk();
    expect(document.head.querySelectorAll('script[data-spotify-sdk]').length).toBe(1);
  });

  it('resolves when window.onSpotifyWebPlaybackSDKReady fires', async () => {
    const promise = loadSpotifySdk();
    window.onSpotifyWebPlaybackSDKReady?.();
    await expect(promise).resolves.toBeUndefined();
  });
});
