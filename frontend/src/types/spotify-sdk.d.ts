// Ambient extensions for window-level Spotify SDK contract.
// `Spotify` global + `Window.Spotify` come from @types/spotify-web-playback-sdk;
// the loader callback is project-specific. We pull the DT package via
// triple-slash reference so the shared `Spotify` namespace is visible
// without adding it to tsconfig's `types` allow-list.
/// <reference types="spotify-web-playback-sdk" />

declare global {
  interface Window {
    onSpotifyWebPlaybackSDKReady?: () => void;
  }
}

export {};
