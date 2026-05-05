const SDK_URL = 'https://sdk.scdn.co/spotify-player.js';

let inflight: Promise<void> | null = null;

export function loadSpotifySdk(): Promise<void> {
  if (inflight) return inflight;
  if (typeof window === 'undefined') return Promise.resolve();
  if (window.Spotify) return Promise.resolve();
  if (document.head.querySelector('script[data-spotify-sdk]')) {
    inflight = waitForReady();
    return inflight;
  }

  inflight = new Promise<void>((resolve, reject) => {
    const prior = window.onSpotifyWebPlaybackSDKReady;
    window.onSpotifyWebPlaybackSDKReady = () => {
      prior?.();
      resolve();
    };
    const tag = document.createElement('script');
    tag.src = SDK_URL;
    tag.async = true;
    tag.dataset.spotifySdk = 'true';
    tag.onerror = () => {
      inflight = null;
      reject(new Error('spotify_sdk_load_failed'));
    };
    document.head.appendChild(tag);
  });

  return inflight;
}

function waitForReady(): Promise<void> {
  return new Promise<void>((resolve) => {
    const prior = window.onSpotifyWebPlaybackSDKReady;
    window.onSpotifyWebPlaybackSDKReady = () => {
      prior?.();
      resolve();
    };
  });
}

export function __resetSdkLoaderForTests(): void {
  inflight = null;
}
