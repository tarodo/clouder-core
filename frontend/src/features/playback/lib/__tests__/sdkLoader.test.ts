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

  it('removes failed script tag and retries cleanly', async () => {
    const promise = loadSpotifySdk();
    // simulate CDN failure
    const tag = document.head.querySelector('script[data-spotify-sdk]') as HTMLScriptElement | null;
    expect(tag).not.toBeNull();
    tag!.dispatchEvent(new Event('error'));
    await expect(promise).rejects.toThrow(/spotify_sdk_load_failed/);

    // retry should inject a fresh tag, not enter waitForReady on the dead one
    expect(document.head.querySelectorAll('script[data-spotify-sdk]').length).toBe(0);
    const retry = loadSpotifySdk();
    expect(document.head.querySelectorAll('script[data-spotify-sdk]').length).toBe(1);
    // resolve the retry to keep the test clean
    window.onSpotifyWebPlaybackSDKReady?.();
    await expect(retry).resolves.toBeUndefined();
  });
});
