// Ambient extensions for window-level Spotify SDK contract.
// `Spotify` global comes from @types/spotify-web-playback-sdk;
// the loader callback is project-specific.
declare global {
  interface Window {
    onSpotifyWebPlaybackSDKReady?: () => void;
  }
}

export {};
